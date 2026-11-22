# excercise-langfuse

Мультиагентная SMM-система на Python, `uv` и LangGraph.

Цепочка:

```text
User -> Strategist -> BriefCreator -> Copywriter -> Editor -> Publisher
                                           ^             |          |
                                           |             v          |
                                           +--- revise ---          |
                                                                  next post
```

После `Editor` работает conditional edge:

- `APPROVE` ведет к `Publisher`;
- `REVISE` возвращает к `Copywriter`;
- максимум `max_revision_cycles` циклов доработки, затем текст все равно уходит к `Publisher`, чтобы не было бесконечного цикла.

## Подготовка

Установите зависимости:

```bash
uv sync
```

Или через `requirements.txt`:

```bash
uv pip install -r requirements.txt
```

Запустите локальную модель в Ollama и проверьте `config.json`:

```json
{
  "model": {
    "provider": "ollama",
    "model": "qwen2.5:7b-instruct",
    "base_url": "http://localhost:11434",
    "temperature": 0.4
  }
}
```

## Запуск

Прямо из консоли:

```bash
uv run smm-agents "Сделай SMM-пост для онлайн-школы Python про набор на курс для новичков"
```

Из файла с запросом:

```bash
uv run smm-agents --request-file request.txt --platform VK
```

## Наблюдение за прогрессом

Для первой версии выбран CLI + файлы результата:

- в консоль печатается каждый шаг графа, решение редактора и счетчик доработок;
- полный лог пишется в `runs/<run_id>/agent.log`;
- каждая готовая публикация сразу после `Publisher` пишется в `runs/<run_id>/posts/post_001.md`, `post_002.md` и т.д.;
- общий файл `runs/<run_id>/final.md` обновляется после каждой готовой публикации;
- промежуточное состояние пишется в `runs/<run_id>/state.partial.json` после каждого шага;
- полное финальное состояние графа пишется в `runs/<run_id>/state.json`.

Во время работы можно смотреть лог:

```bash
tail -f runs/<run_id>/agent.log
```

Такой запуск проще, чем веб-интерфейс, и уже хорошо показывает прогресс. Веб-поле ввода с polling `tail 20` можно добавить следующим шагом поверх этой же CLI-логики.
