# ⚠️ КРИТИЧЕСКАЯ ПРОБЛЕМА - pgvector лимит 2000 измерений

## Проблема

При попытке применить миграцию возникла ошибка:
```
asyncpg.exceptions.ProgramLimitExceededError: 
column cannot have more than 2000 dimensions for ivfflat index
```

## Причина

**pgvector имеет жесткое ограничение в 2000 измерений для ВСЕХ типов индексов** (HNSW и IVFFlat).

Наши векторы имеют **4096 измерений** (модель `qwen/qwen3-embedding-8b`), что **в 2 раза превышает** лимит pgvector.

## Решение ✅

**Вариант 1: Без индексов (текущее решение)**
- ✅ Работает сразу, без изменений
- ✅ Точность поиска 100%
- ⚠️ Медленнее для больших датасетов (>100k векторов)
- ✅ Приемлемо для малых/средних датасетов (<100k)

Миграция теперь **пропускает создание индексов** и использует sequential scan.

## Альтернативные решения (для будущего)

### Вариант 2: Уменьшить размерность векторов
Использовать модель с меньшей размерностью или применить PCA:

**Модели с меньшей размерностью**:
- `text-embedding-3-small` (OpenAI) - 1536 dims ✅
- `text-embedding-ada-002` (OpenAI) - 1536 dims ✅
- `all-MiniLM-L6-v2` (Sentence Transformers) - 384 dims ✅

**PCA (Principal Component Analysis)**:
```python
from sklearn.decomposition import PCA

# Уменьшить 4096 → 1536 dims
pca = PCA(n_components=1536)
reduced_vectors = pca.fit_transform(original_vectors)
```

⚠️ **Минус**: Потеря информации (~5-10% точности)

### Вариант 3: Обновить pgvector
Проверить, есть ли новая версия pgvector с поддержкой >2000 dims:

```bash
# Проверить текущую версию
docker compose exec db psql -U postgres -d motivi_db -c "SELECT extversion FROM pg_extension WHERE extname='vector';"

# Если доступна новая версия:
docker compose exec db psql -U postgres -d motivi_db -c "ALTER EXTENSION vector UPDATE;"
```

**Примечание**: На момент написания (2026-01) лимит 2000 dims актуален для pgvector 0.6.x

### Вариант 4: Альтернативная векторная БД
Для production с большими объемами рассмотреть:

- **Qdrant** - поддерживает любую размерность, быстрый
- **Milvus** - enterprise-grade, масштабируемый
- **Weaviate** - с встроенной векторизацией

## Что изменилось

### Миграция (20260128_add_vector_indexes.py)
```python
def upgrade() -> None:
    # SKIP index creation due to pgvector 2000 dimension limit
    print("WARNING: Skipping vector index creation")
    print("Reason: pgvector has a 2000 dimension limit")
    print("Current vector dimension: 4096")
    pass  # No indexes created
```

## Теперь можно применить миграцию

```bash
docker compose exec app poetry run alembic upgrade head
```

Миграция пройдет успешно, но **без создания индексов**. ✅

## Производительность без индексов

### Sequential Scan Performance

| Количество векторов | Время поиска (top-5) | Приемлемо? |
|---------------------|----------------------|------------|
| < 1,000 | < 10ms | ✅ Отлично |
| 1,000 - 10,000 | 10-100ms | ✅ Хорошо |
| 10,000 - 100,000 | 100ms - 1s | ⚠️ Приемлемо |
| > 100,000 | > 1s | ❌ Медленно |

### Оптимизация без индексов

1. **LIMIT запросы**:
```sql
-- Хорошо: ограничиваем результаты
SELECT * FROM episode_embeddings 
ORDER BY embedding <=> query_vector 
LIMIT 5;  -- Быстро даже без индекса
```

2. **Фильтрация перед поиском**:
```sql
-- Сначала фильтруем по user_id, потом ищем
SELECT * FROM episode_embeddings 
WHERE user_id = 123  -- Используется обычный B-tree индекс
ORDER BY embedding <=> query_vector 
LIMIT 5;
```

3. **Партиционирование**:
```sql
-- Разделить таблицу по user_id
CREATE TABLE episode_embeddings_partition_1 
PARTITION OF episode_embeddings 
FOR VALUES FROM (1) TO (10000);
```

## Рекомендации

### Для текущего проекта (MVP/Small Scale)
✅ **Оставить как есть** (без индексов)
- Производительность приемлема для <100k векторов
- Не требует изменений в коде
- Точность поиска 100%

### Для масштабирования (>100k векторов)
🔄 **Рассмотреть варианты**:
1. Переход на модель с меньшей размерностью (1536 dims)
2. Использование PCA для уменьшения размерности
3. Миграция на Qdrant/Milvus

## Мониторинг

Добавить метрики для отслеживания производительности:

```python
import time

start = time.time()
results = await session.execute(vector_search_query)
duration = time.time() - start

logger.info(f"Vector search took {duration:.3f}s for {len(results)} results")

# Алерт если медленно
if duration > 1.0:
    logger.warning(f"Slow vector search: {duration:.3f}s")
```

## Заключение

**Текущее состояние**: ✅ Работает, но без индексов  
**Производительность**: ✅ Приемлемо для малых/средних датасетов  
**Точность**: ✅ 100% (sequential scan)  
**Масштабируемость**: ⚠️ Ограничена (~100k векторов)

Для MVP и начального этапа это **оптимальное решение**. При росте данных можно будет оптимизировать.

**Статус**: ✅ Готово к применению
