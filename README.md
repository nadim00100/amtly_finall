# Data Directory

This directory contains all application data including the database, knowledge base, and temporary uploads.

---

## 📁 Directory Structure

```
data/
├── knowledge_base/
│   ├── documents/          # Source PDF documents
│   ├── chunks/            # Processed text chunks (JSONL)
│   ├── embeddings/        # Vector embeddings (Chroma DB)
│   └── ingestion_progress.json
├── uploads/               # Temporary file uploads
├── schemas/              # Form schemas (future use)
└── amtly.db             # SQLite database
```

---

## 🗄️ Database (amtly.db)

**SQLite database containing:**
- Chat sessions
- Message history
- Conversation metadata

**Schema:**
- `chats` table: Chat sessions with titles and timestamps
- `messages` table: Individual messages with sources and metadata

**Backup:**
```bash
# Create backup
cp data/amtly.db data/amtly.db.backup

# Restore backup
cp data/amtly.db.backup data/amtly.db
```

---

## 📚 Knowledge Base

### documents/
Place your PDF documents here for ingestion:
```bash
data/knowledge_base/documents/
├── buergergeld_info.pdf
├── jobcenter_guide.pdf
└── wba_form_instructions.pdf
```

**Supported formats:**
- PDF documents (text or scanned)

### chunks/
Automatically generated JSONL files containing processed chunks:
```bash
data/knowledge_base/chunks/
├── buergergeld_info_chunks.jsonl
└── jobcenter_guide_chunks.jsonl
```

**Format:** One JSON object per line
```json
{"content": "...", "metadata": {...}}
```

### embeddings/
Chroma vector database files (automatically generated):
```bash
data/knowledge_base/embeddings/
└── [Chroma DB files]
```

**Do not manually edit these files.**

---

## 📤 Uploads Directory

Temporary storage for uploaded files:
- Files are processed and then can be deleted
- Cleared on application restart (optional)
- Not backed up

---

## 🚀 Ingesting Documents

### Step 1: Add PDFs
```bash
cp your-document.pdf data/knowledge_base/documents/
```

### Step 2: Run Ingestion Script
```bash
python ingest_documents.py
```

This will:
1. Extract text from PDFs
2. Clean and chunk the text
3. Generate embeddings
4. Store in vector database

### Step 3: Verify
```bash
python ingest_documents.py list
```

---

## 🔄 Managing the Knowledge Base

### List all documents
```bash
python ingest_documents.py list
```

### Force re-process all documents
```bash
python ingest_documents.py force
```

### Reset everything
```bash
python ingest_documents.py reset
```

⚠️ **Warning:** Reset deletes all processed data!

---

## 📊 Storage Requirements

**Typical sizes:**
- SQLite database: 1-10 MB (depends on message history)
- Knowledge base embeddings: 50-500 MB (depends on documents)
- Temporary uploads: Varies (cleared regularly)

**Recommended free space:** 1 GB minimum

---

## 🔒 Data Privacy

- **Local storage only** - no cloud uploads
- **Temporary files** - deleted after processing
- **Database backups** - your responsibility
- **Sensitive documents** - ensure proper file permissions

---

## 🧹 Cleaning Up

### Clear temporary uploads
```bash
rm -rf data/uploads/*
touch data/uploads/.gitkeep
```

### Clear knowledge base
```bash
rm -rf data/knowledge_base/embeddings/*
rm -rf data/knowledge_base/chunks/*
python ingest_documents.py force
```

### Reset database
```bash
rm data/amtly.db
python app.py  # Will recreate
```

---

## 🔍 Monitoring

### Check database size
```bash
ls -lh data/amtly.db
```

### Check knowledge base status
```bash
python -c "from services.vector_store import vector_store; print(vector_store.get_collection_info())"
```

### Check number of chats
```bash
sqlite3 data/amtly.db "SELECT COUNT(*) FROM chats;"
```

### Check number of messages
```bash
sqlite3 data/amtly.db "SELECT COUNT(*) FROM messages;"
```

---

## 🛡️ Backup Strategy

### Daily Backup
```bash
# Create backup
DATE=$(date +%Y%m%d)
cp data/amtly.db backups/amtly_$DATE.db
```

### Automated Backup Script
```bash
#!/bin/bash
# backup.sh
DATE=$(date +%Y%m%d)
mkdir -p backups
cp data/amtly.db backups/amtly_$DATE.db
echo "Backup created: backups/amtly_$DATE.db"
```

---

## 📝 Notes

- `.gitkeep` files ensure empty directories are tracked in git
- Database contains no sensitive information by design
- Knowledge base documents may contain official information
- Temporary uploads should not contain personal information
- Regular backups recommended for production use

---

## 🆘 Troubleshooting

### Database locked
```bash
# Close all connections and restart app
```

### Knowledge base empty
```bash
# Check documents exist
ls data/knowledge_base/documents/

# Re-run ingestion
python ingest_documents.py force
```

### Out of disk space
```bash
# Check usage
du -sh data/*

# Clean up if needed
```

---

## 📖 Additional Resources

- **Database Schema:** See `models/database.py`
- **Vector Store:** See `services/vector_store.py`
- **Ingestion:** See `ingest_documents.py`
- **Configuration:** See `config.py`

---

**For more information, see the main [README.md](../README.md)**