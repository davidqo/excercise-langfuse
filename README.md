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

Настройте Langfuse через переменные окружения:

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"
```

Можно также положить эти переменные в локальный `.env` в корне проекта: приложение загрузит его автоматически.
Для self-hosted Langfuse укажите свой `LANGFUSE_HOST`.
Если ключи не заданы, приложение продолжит работать, но Langfuse client будет отключен и traces не отправятся.

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

Дополнительно запуск трассируется в Langfuse:

- `smm_pipeline` показывает длительность всего пайплайна `graph.invoke`;
- вложенные `generation`-наблюдения `Strategist`, `BriefCreator`, `Copywriter`, `Editor`, `Publisher` показывают длительность отдельных обращений к LLM;
- в metadata общего span пишутся `run_id`, модель и лимит циклов доработки.

В консоль и `runs/<run_id>/agent.log` пишутся диагностические сообщения Langfuse:

- `Langfuse enabled: host=...` означает, что ключи найдены и tracing включен;
- `Langfuse disabled: missing env vars: ...` показывает, каких переменных окружения не хватает;
- `Langfuse pipeline span started/finished` и `Langfuse LLM generation started/finished` подтверждают создание наблюдений;
- `Langfuse flush started/finished` подтверждает отправку накопленных событий в конце запуска.

Во время работы можно смотреть лог:

```bash
tail -f runs/<run_id>/agent.log
```

Такой запуск проще, чем веб-интерфейс, и уже хорошо показывает прогресс. Веб-поле ввода с polling `tail 20` можно добавить следующим шагом поверх этой же CLI-логики.
