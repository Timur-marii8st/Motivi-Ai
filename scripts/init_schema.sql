-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    tg_user_id INTEGER NOT NULL UNIQUE,
    tg_chat_id INTEGER NOT NULL,
    name TEXT,
    age INTEGER,
    user_timezone TEXT,
    wake_time TIME WITHOUT TIME ZONE,
    bed_time TIME WITHOUT TIME ZONE,
    occupation_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create core_memory table
CREATE TABLE IF NOT EXISTS core_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    core_text TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create core_memory_embeddings table
CREATE TABLE IF NOT EXISTS core_memory_embeddings (
    id SERIAL PRIMARY KEY,
    core_memory_id INTEGER NOT NULL UNIQUE REFERENCES core_memory(id),
    embedding VECTOR(1536) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create working_memory table
CREATE TABLE IF NOT EXISTS working_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create working_memory_embeddings table
CREATE TABLE IF NOT EXISTS working_memory_embeddings (
    id SERIAL PRIMARY KEY,
    working_memory_id INTEGER NOT NULL UNIQUE REFERENCES working_memory(id),
    embedding VECTOR(1536) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);