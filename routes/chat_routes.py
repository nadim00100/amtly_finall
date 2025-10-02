"""
Chat Routes - Main chat functionality
FIXED VERSION with enhanced form helper integration
"""

from flask import Blueprint, request, jsonify, session
from models.database import (
    db, Chat, get_or_create_default_chat, add_message_to_chat,
    get_chat_messages, update_chat_context
)
from services.openai_service import openai_service
from services.language_detection import language_service
from core.chat_handler import rag_chat_handler
from core.document_processor import document_processor
from core.enhanced_form_helper import enhanced_form_helper
from utils.validation import validation_utils
from utils.response_formatter import response_formatter

chat_bp = Blueprint('chat', __name__)


def detect_user_intent(message):
    """Detect what user wants to do with the document"""
    if not message:
        return {'explain': True, 'translate': False}

    message_lower = message.lower()

    wants_explanation = any(word in message_lower for word in [
        'explain', 'erkläre', 'erklären', 'analyse', 'analyze',
        'what is', 'was ist', 'tell me', 'sag mir', 'describe', 'beschreib'
    ])

    wants_translation = any(word in message_lower for word in [
        'translate', 'übersetze', 'übersetz', 'translation', 'übersetzung',
        'in english', 'auf englisch', 'in german', 'auf deutsch'
    ])

    if not wants_explanation and not wants_translation:
        wants_explanation = True

    return {
        'explain': wants_explanation,
        'translate': wants_translation
    }


def is_simple_file_command(message):
    """
    Detect if user message is just a simple command about the uploaded file
    These commands should be handled by file processor only, not RAG
    """
    if not message:
        return False

    message_lower = message.strip().lower()

    # Very short commands (1-2 words)
    simple_commands = [
        'translate', 'übersetze', 'übersetz',
        'explain', 'erkläre', 'erklär',
        'summarize', 'zusammenfassen', 'summary',
        'analyse', 'analyze', 'analysiere',
        'read', 'lies', 'lesen',
        'what is this', 'was ist das',
        'tell me', 'sag mir',
    ]

    # Check if message is exactly one of these commands or very close
    for cmd in simple_commands:
        if message_lower == cmd or message_lower == cmd + '.':
            return True

    # Check for short commands with "this" or "it"
    short_patterns = [
        'translate this', 'translate it',
        'explain this', 'explain it',
        'summarize this', 'summarize it',
        'what is this', "what's this",
        'übersetze das', 'erkläre das',
        'was ist das', 'analysiere das',
    ]

    if message_lower in short_patterns:
        return True

    # If message is very short (< 15 chars) and contains translate/explain
    if len(message_lower) < 15:
        if any(word in message_lower for word in ['translate', 'übersetze', 'explain', 'erkläre', 'summary']):
            return True

    return False


def route_user_message(user_message, conversation_history=None):
    """
    Smart routing using enhanced form helper
    """

    # 1. Use enhanced form detection with better algorithm
    form_detection = enhanced_form_helper.detect_form_and_field(user_message)

    # Check if we detected a form with reasonable confidence
    if form_detection['form_code'] and form_detection['confidence'] in ['high', 'medium']:
        return 'form'

    # 2. If field/section mentioned but no form, check conversation context
    #    (User might be asking follow-up: "What about field 3?" after discussing HA)
    if (form_detection['field'] or form_detection['section']) and conversation_history:
        # Look back through recent messages for form mentions
        for msg in reversed(conversation_history[-3:]):
            if msg['role'] == 'assistant':
                # Check if any form code was mentioned
                for code in ['HA', 'WBA', 'VM', 'KDU', 'WEP', 'WEH', 'KI']:
                    if code in msg['content']:
                        return 'form'  # Continue form discussion

    # 3. Check for German institution emails
    if language_service.is_german_institution_request(user_message):
        return 'rag_german_email'

    # 4. Default to general RAG
    return 'rag_general'


def handle_direct_openai_fallback(user_message, language, conversation_history=None):
    """Fallback when both form helper and RAG fail"""
    conv_context = ""
    if conversation_history and len(conversation_history) > 1:
        # Use more context for better follow-up handling
        recent = conversation_history[-6:]
        conv_lines = []
        for idx, msg in enumerate(recent):
            role = "User" if msg['role'] == 'user' else "Assistant"
            # Keep more content for recent messages
            if idx >= len(recent) - 2:
                content = msg['content'][:200] if len(msg['content']) > 200 else msg['content']
            else:
                content = msg['content'][:120] if len(msg['content']) > 120 else msg['content']
            conv_lines.append(f"{role}: {content}")

        if language == 'de':
            conv_context = f"""

=== GESPRÄCHSKONTEXT ===
{chr(10).join(conv_lines)}

⚠️ WICHTIG: Nutze diesen Kontext für Folgefragen!
- Bei kurzen Fragen (1-3 Wörter) → Beziehe dich auf vorheriges Thema
- Bei "das", "es", "dies" → Beziehe dich auf den vorherigen Kontext
- Bei "mehr", "kürzer", "anders" → Passe deine letzte Antwort an"""
        else:
            conv_context = f"""

=== CONVERSATION CONTEXT ===
{chr(10).join(conv_lines)}

⚠️ IMPORTANT: Use this context for follow-up questions!
- For short questions (1-3 words) → Refer to previous topic
- For "it", "that", "this" → Refer to previous context
- For "more", "shorter", "different" → Adjust your last answer"""

    if language == 'de':
        system_prompt = f"""Du bist Amtly, ein KI-Assistent für deutsche Bürokratie.{conv_context}

Du hilfst bei:
- Allgemeine Jobcenter-Fragen und -Regeln
- E-Mail-Verfassung (formeller deutscher Stil)
- Dokumentenübersetzung und -erklärung
- Bürokratische Prozesse und Vorschriften

Sei hilfreich, klar und professionell. Nutze den Gesprächskontext oben für Folgefragen!"""
    else:
        system_prompt = f"""You are Amtly, an AI assistant for German bureaucracy.{conv_context}

You help with:
- General Jobcenter questions and rules
- Email writing (formal German style)
- Document translation and explanation
- Bureaucratic processes and regulations

Be helpful, clear, and professional. Use the conversation context above for follow-ups!"""

    try:
        result = openai_service.get_response(user_message, system_prompt)
        return result['response'] if result['success'] else "❌ I encountered an error. Please try again."
    except Exception as e:
        print(f"OpenAI fallback error: {e}")
        return "❌ I encountered an error. Please try again."


@chat_bp.route('/chat', methods=['POST'])
def chat():
    """Main chat endpoint - handles text messages and file uploads"""
    try:
        # Get chat_id
        chat_id = request.form.get('chat_id')
        if not chat_id:
            chat_obj = get_or_create_default_chat()
            chat_id = chat_obj.id
        else:
            chat_id = int(chat_id)
            chat_obj = db.session.get(Chat, chat_id)
            if not chat_obj:
                return jsonify({'error': 'Chat not found'}), 404

        # Get inputs
        user_message = request.form.get('message', '').strip() if request.form.get('message') else None
        files = request.files.getlist('files')

        # Get context - INCREASED for better follow-ups
        document_context = chat_obj.document_context or ''
        conversation_history = get_chat_messages(chat_id, limit=12)

        # Validation
        if not user_message and not files:
            error_response = response_formatter.format_error_response(
                "Please provide a message or upload a file.", 'validation_error'
            )
            return jsonify(error_response), 400

        if user_message:
            is_valid, error = validation_utils.validate_chat_message(user_message)
            if not is_valid:
                error_response = response_formatter.format_error_response(error, 'validation_error')
                return jsonify(error_response), 400

        # Add user message to database
        file_info = None
        if user_message:
            if files:
                total_size = sum(file.content_length or 0 for file in files)
                file_info = {
                    'count': len(files),
                    'filenames': [file.filename for file in files],
                    'total_size': total_size
                }

            add_message_to_chat(
                chat_id=chat_id,
                role='user',
                content=user_message,
                file_info=file_info
            )

        response_text = ""
        sources = []
        message_type = 'chat'

        # Detect language and intent
        try:
            user_language = language_service.get_response_language(user_message) if user_message else 'en'
            user_intent = detect_user_intent(user_message) if user_message else {'explain': True, 'translate': False}
            is_german_institution_email = language_service.is_german_institution_request(
                user_message) if user_message else False
        except Exception as e:
            print(f"Language detection error: {e}")
            user_language = 'en'
            user_intent = {'explain': True, 'translate': False}
            is_german_institution_email = False

        if is_german_institution_email:
            user_language = 'de'

        # ====================================================================
        # PROCESS MULTIPLE UPLOADED FILES
        # ====================================================================
        if files:
            response_text, sources = process_uploaded_files(
                files, user_language, user_intent, conversation_history
            )

            if response_text:
                document_context = response_text[:4000]
                update_chat_context(chat_id, document_context=document_context)
                message_type = 'document'

        # ====================================================================
        # PROCESS TEXT MESSAGE - Skip if simple file command
        # ====================================================================
        if user_message:
            # Check if this is just a simple file command
            is_simple_cmd = files and is_simple_file_command(user_message)

            if not is_simple_cmd:
                text_response, text_sources, msg_type = process_text_message(
                    user_message, document_context, user_language,
                    conversation_history, response_text
                )

                if text_response:
                    response_text = f"{response_text}\n\n---\n\n{text_response}" if response_text else text_response
                    sources.extend(text_sources)
                    if not files:
                        message_type = msg_type
            else:
                # Simple file command - file processing was enough
                print(f"ℹ️ Simple file command detected: '{user_message}' - skipping RAG")

        # Add assistant response to database
        add_message_to_chat(
            chat_id=chat_id,
            role='assistant',
            content=response_text,
            sources=sources,
            message_type=message_type,
            used_knowledge_base=bool(sources)
        )

        # Format response
        formatted_response = response_formatter.format_chat_response(
            response_text,
            sources=sources if sources else [],
            response_type=message_type
        )

        formatted_response["chat_id"] = chat_id
        if document_context:
            formatted_response["document_text"] = document_context

        return jsonify(formatted_response)

    except Exception as e:
        print(f"Chat error: {e}")
        import traceback
        traceback.print_exc()
        error_response = response_formatter.format_error_response(
            "An unexpected error occurred.", 'server_error'
        )
        return jsonify(error_response), 500


def process_uploaded_files(files, user_language, user_intent, conversation_history):
    """Process multiple uploaded files and return combined analysis"""
    try:
        all_extracted_texts = []
        processed_files = []

        for idx, file in enumerate(files):
            print(f"Processing file {idx + 1}/{len(files)}: {file.filename}")

            # Validate file
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)

            file_info_dict = {
                'name': file.filename,
                'size': file_size
            }

            is_valid, error = validation_utils.validate_file_upload(file_info_dict)
            if not is_valid:
                print(f"File {file.filename} validation failed: {error}")
                continue

            # Process document
            try:
                file_path = document_processor.save_uploaded_file(file)
                extracted_text = document_processor.process_document(file_path)
                file_path.unlink()

                if extracted_text:
                    all_extracted_texts.append({
                        'filename': file.filename,
                        'text': extracted_text,
                        'page_number': idx + 1
                    })
                    processed_files.append(file.filename)
                    print(f"✅ Extracted {len(extracted_text)} chars from {file.filename}")
            except Exception as e:
                print(f"❌ Error processing {file.filename}: {e}")
                continue

        # Check if we got any text
        if all_extracted_texts:
            # Combine all texts with page markers
            combined_text = ""
            for item in all_extracted_texts:
                if len(files) > 1:
                    combined_text += f"\n\n--- PAGE {item['page_number']} ({item['filename']}) ---\n\n"
                combined_text += item['text']

            # Build conversation context
            conv_context = ""
            if conversation_history and len(conversation_history) > 1:
                # Take more context for file-related follow-ups
                recent = conversation_history[-6:]
                conv_lines = []
                for idx, msg in enumerate(recent):
                    role = 'User' if msg['role'] == 'user' else 'Assistant'
                    # Keep more content for recent messages
                    if idx >= len(recent) - 2:
                        content = msg['content'][:300] if len(msg['content']) > 300 else msg['content']
                    else:
                        content = msg['content'][:150] if len(msg['content']) > 150 else msg['content']
                    conv_lines.append(f"{role}: {content}")

                conv_context = f"\n\n=== CONVERSATION HISTORY ===\n{chr(10).join(conv_lines)}\n"
                conv_context += "\n⚠️ Use this history to understand follow-up requests about the document!\n"

            # Create system prompt
            if len(files) > 1:
                file_context = f"This is a multi-page document ({len(files)} pages/files). "
            else:
                file_context = "This is a document. "

            if user_language == 'de':
                if user_intent['explain'] and user_intent['translate']:
                    system_prompt = f"""Du bist Amtly.{conv_context}

{file_context}Aufgabe: Erkläre UND übersetze dieses Dokument.

WICHTIG für Folgefragen:
- "Kürzer" → Fasse deine vorherige Analyse kürzer zusammen
- "Mehr Details" → Gib mehr Details zu deiner vorherigen Erklärung
- "Was bedeutet [Begriff]?" → Erkläre spezifische Begriffe aus dem Dokument
- "Nur übersetzen" → Gib nur die Übersetzung, keine Erklärung
- "In Englisch" → Übersetze deine vorherige Antwort ins Englische"""
                elif user_intent['translate']:
                    system_prompt = f"Du bist Amtly.{conv_context}\n\n{file_context}Übersetze NUR (keine Erklärung)."
                else:
                    system_prompt = f"Du bist Amtly.{conv_context}\n\n{file_context}Erkläre das Dokument (NICHT übersetzen)."
            else:
                if user_intent['explain'] and user_intent['translate']:
                    system_prompt = f"""You are Amtly.{conv_context}

{file_context}Task: Explain AND translate this document.

IMPORTANT for follow-ups:
- "Shorter" → Summarize your previous analysis more briefly
- "More details" → Provide more details about your previous explanation
- "What does [term] mean?" → Explain specific terms from the document
- "Just translate" → Provide only translation, no explanation
- "In German" → Translate your previous answer to German"""
                elif user_intent['translate']:
                    system_prompt = f"You are Amtly.{conv_context}\n\n{file_context}Translate ONLY (no explanation)."
                else:
                    system_prompt = f"You are Amtly.{conv_context}\n\n{file_context}Explain the document (do NOT translate)."

            result = openai_service.get_response(
                f"Analyze this document:\n\n{combined_text[:3000]}",
                system_prompt
            )

            if result['success']:
                if len(files) > 1:
                    prefix = f"📄 **Multi-Page Document Analysis ({len(files)} pages):**\n\n"
                else:
                    prefix = "📄 **Document Analysis:**\n\n"
                response_text = prefix + result['response']
            else:
                response_text = "📄 Documents processed but had trouble analyzing them."

            return response_text, processed_files
        else:
            return "❌ Couldn't extract text from any files. Ensure documents are clear.", []

    except Exception as e:
        print(f"File processing error: {e}")
        return f"❌ Error processing files: {str(e)}", []


def process_text_message(user_message, document_context, user_language, conversation_history, existing_response):
    """
    Process text message with improved form routing
    """
    route = route_user_message(user_message, conversation_history)
    sources = []
    message_type = 'chat'

    # ====================================================================
    # Try enhanced form helper
    # ====================================================================
    if route == 'form':
        form_result = enhanced_form_helper.help_with_form(
            user_message,
            conversation_history=conversation_history
        )

        if form_result['success']:
            # Extract metadata for rich display
            form_code = form_result.get('form', 'Form')
            field = form_result.get('field', '')
            section = form_result.get('section', '')
            metadata = form_result.get('metadata', {})

            # Build enhanced response
            form_response = f"📝 **{form_code} Form Help"

            if field:
                field_label = metadata.get('field_label', f'Field {field}')
                form_response += f" - {field_label}"

                # Highlight critical/required fields
                if metadata.get('critical'):
                    form_response += " ⚠️ CRITICAL**"
                elif metadata.get('required'):
                    form_response += " (required)**"
                else:
                    form_response += "**"

            elif section:
                form_response += f" - Section {section}**"
            else:
                form_response += "**"

            form_response += f"\n\n{form_result['response']}"

            return form_response, sources, 'form'
        else:
            # Form helper failed, fall back to RAG
            print(f"Form helper failed: {form_result.get('error')}")
            route = 'rag_general'

    # ====================================================================
    # Try RAG
    # ====================================================================
    if route.startswith('rag'):
        effective_language = 'de' if route == 'rag_german_email' else user_language

        try:
            rag_result = rag_chat_handler.generate_rag_response(
                user_message, document_context, effective_language,
                conversation_history=conversation_history
            )

            if rag_result and rag_result.get('success'):
                response = rag_result['response']
                if rag_result.get('sources'):
                    sources = rag_result['sources']
                return response, sources, 'chat'
            else:
                # Fallback to direct OpenAI
                response = handle_direct_openai_fallback(
                    user_message, effective_language, conversation_history
                )
                return response, sources, 'chat'

        except Exception as e:
            print(f"RAG error: {e}")
            response = handle_direct_openai_fallback(
                user_message, effective_language, conversation_history
            )
            return response, sources, 'chat'

    return "", sources, 'chat'


@chat_bp.route('/clear_session', methods=['POST'])
def clear_session():
    """Clear user session"""
    try:
        session.clear()
        return jsonify({"message": "Session cleared successfully", "status": "success"})
    except Exception as e:
        error_response = response_formatter.format_error_response(
            "Failed to clear session", 'session_error'
        )
        return jsonify(error_response), 500