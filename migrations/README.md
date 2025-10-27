# Database Migrations

This folder contains database migration scripts for WorldReasoner.

## Available Migrations

### `add_article_metadata.py`
Adds the `metadata` column to the `articles` table.

**When to run:** If you have an existing database created before the Evidence Pipeline was added, and you encounter the error:
```
sqlite3.OperationalError: table articles has no column named metadata
```

**How to run:**
```bash
python migrations/add_article_metadata.py
```

The script will:
1. Check if the column already exists (safe to run multiple times)
2. Add the `metadata` column if needed
3. Set default value to `'{}'` (empty JSON object)

## How Migrations Work

WorldReasoner uses SQLite with Pydantic models. When you add a new field to a model:

1. **New databases**: The field is automatically included when the table is created
2. **Existing databases**: You need to run a migration to alter the table

## Creating New Migrations

If you add a new field to a model:

1. Create a new migration script in this folder
2. Use the pattern from existing migrations
3. Always check if the column exists before adding
4. Document the migration in this README

## Troubleshooting

**Error: "table X has no column named Y"**
- A new field was added to a model
- Your database was created before this change
- Run the appropriate migration script

**Error: "no such table: X"**
- This is normal if you haven't used that part of the system yet
- The table will be created automatically when you first use it
- No migration needed
