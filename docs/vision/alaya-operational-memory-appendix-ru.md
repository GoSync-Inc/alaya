# Технический аппендикс к концепции Alaya

Черновик технического приложения  
Язык: русский  
Статус: working draft  
Назначение: дополнение к концептуальному white paper про Alaya как `Operational Memory and Workflow Engine for AI Assistants`

## 1. Зачем нужен этот аппендикс

Основной white paper описывает идею Alaya на концептуальном уровне.

Этот документ отвечает на более прикладные вопросы:

- как такая система может быть устроена технически
- что в текущей Alaya уже похоже на сильное ядро
- что именно отличает ее от популярных open-source memory systems
- где в этой архитектуре может быть настоящее know-how

## 2. В одном абзаце

Технически Alaya можно понимать как систему из четырех связанных контуров:

1. `ingest` — сбор событий из чатов, встреч, аудио и интеграций  
2. `memory` — перевод событий в структурированное состояние  
3. `reasoning` — извлечение смысла, сущностей, фактов, связей и статусов  
4. `execution` — напоминания, delayed tasks, recurring jobs, workflows и follow-ups

Ключевая идея не в том, чтобы просто хранить память агента, а в том, чтобы поддерживать рабочее состояние мира и запускать действия от изменений этого состояния.

## 3. Что уже выглядит сильным в текущем подходе Alaya

Даже в текущем продуктово-доменном виде у Alaya уже просматривается сильная архитектурная линия:

- сырые события хранятся отдельно от извлеченного знания
- память строится по стадиям, а не одной магической LLM-операцией
- есть разделение между `declared` и `inferred` состоянием
- есть provenance, то есть связь выводов с источником
- есть delayed/recurring execution через очередь и scheduler
- workflows могут запускаться не только по времени, но и потенциально по изменениям сущностей и фактов

Именно последняя часть особенно важна.  
Она смещает Alaya из категории "memory layer" в категорию "operational system".

## 4. Техническая модель Alaya

Ниже более приземленная схема того, как такой core устроен.

### 4.1. L0: Raw Event Log

На вход система получает события из разных источников:

- Slack / Telegram messages
- voice notes
- meeting transcripts
- summaries из PLAUD
- calendar events
- updates из задач, документов, CRM и других интеграций

Каждое событие должно сохраняться в raw виде:

- с source id
- source timestamp
- raw payload
- actor
- ACL / visibility
- content hash для deduplication

Это нужно для:

- воспроизводимости
- provenance
- переобработки
- безопасной эволюции extraction pipeline

### 4.2. L0.5: Chunking и gating

После сохранения raw events система:

- извлекает raw text
- разбивает событие на смысловые фрагменты
- классифицирует их по важности и домену

Эта стадия нужна, чтобы:

- не гнать все подряд в дорогой extraction
- выделять только содержательно важные куски
- накапливать cheap signals для последующей обработки

### 4.3. L1: Canonical Entities

Следующий слой это не просто "найденные факты", а канонические сущности.

В B2B-домене это могут быть:

- person
- team
- goal
- project
- task
- decision

В relationship-домене это уже другие типы:

- person
- relationship
- agreement
- followup
- goal
- preference
- important_date
- tension
- unresolved_topic
- date_plan

Ключевой момент:

- сущности должны иметь стабильные идентификаторы
- поддерживать entity resolution
- поддерживать версии и temporal updates

### 4.4. L2: Facts и state transitions

Поверх сущностей система хранит факты и изменения состояния.

Примеры:

- "обещал сделать X до пятницы"
- "важная дата через 3 дня"
- "тема осталась незакрытой"
- "человек предпочитает обсуждать это заранее"
- "в разговоре был конфликтный сигнал"

Именно здесь важно различать:

- declared facts
- inferred facts
- stale facts
- contradicted facts
- superseded facts

### 4.5. L3/L4: Retrieval, review, execution

Дальше память используется не только для поиска, но и для работы:

- semantic retrieval
- graph traversal
- summaries
- weekly reviews
- next-action generation
- reminders
- workflow execution

Именно это и делает систему operational.

## 5. Почему TaskIQ, delayed tasks и cron здесь не "просто инфраструктура"

В более слабых memory systems выполнение часто живет отдельно от памяти.

Например:

- memory что-то запомнила
- агент потом когда-нибудь это нашел
- если повезло, пользователь сам спросил про это вовремя

В operational memory это недостаточно.

Нужны first-class execution primitives:

- one-time delayed jobs
- recurring jobs
- retry semantics
- idempotency
- recovery cron
- fan-out jobs
- memory-triggered workflows

То есть по сути нужен `workflow runtime`, который связан с памятью.

Это может работать так:

- новое обязательство -> планируется follow-up task
- approaching deadline -> ставится reminder
- stale entity -> попадает в weekly review pipeline
- unresolved topic aging -> создается suggestion или check-in
- user correction -> перезапускается downstream recalculation

Это уже не просто планировщик задач.  
Это execution layer, который живет на состоянии памяти.

## 6. Предлагаемый минимальный стек для такого core

Ниже не "единственно правильный" стек, а практический baseline, который уже хорошо соответствует текущему направлению Alaya.

### Backend

- `Python 3.13`
- `FastAPI`
- `uvicorn`

Почему:

- зрелая экосистема
- быстрый путь к API, workers и connectors
- хорошо подходит и для internal product, и для platform core

### Primary storage

- `PostgreSQL`

Почему:

- strong transactional core
- JSONB для гибких domain payloads
- удобно хранить canonical entities, schedules, provenance metadata

### Semantic search

- `pgvector`

Почему:

- достаточно для первого этапа
- не требует отдельной векторной инфраструктуры
- хорошо ложится рядом с transactional data

### Optional graph layer

- `FalkorDB` или другой graph storage как optional модуль

Почему:

- полезно для relation-heavy domains
- но не обязательно как базовое условие первого релиза ядра

### Queue / scheduling

- `Redis`
- `TaskIQ`

Почему:

- async-friendly
- нормальный delayed scheduling
- достаточно легкий compared to Celery
- хорошо ложится на event ingestion, extraction jobs, retries, reminders и workflows

### LLM / extraction runtime

Вариант для Anthropic-first:

- `Anthropic` как основной reasoning/extraction provider
- локальный speech-to-text отдельно, если нужен

Вариант для multi-provider:

- provider abstraction
- отдельные модели для:
  - cheap classification
  - extraction
  - consolidation
  - weekly review / heavy synthesis

### Interfaces

- HTTP API
- Python SDK
- MCP server
- adapters для Telegram / Slack / других агентных оболочек

## 7. Как это может быть выделено в более универсальный core

Если смотреть на Alaya не как на один B2B-продукт, а как на платформенное ядро, то логично разделить систему на три слоя.

### 7.1. Alaya Core

Должно содержать:

- event log
- chunking / gating
- extraction interfaces
- canonical entity store
- fact store
- provenance model
- schedule engine
- workflow triggers
- retrieval APIs
- evaluation primitives

### 7.2. Alaya Connectors

Отдельные адаптеры:

- Slack
- Telegram
- PLAUD import
- local transcript ingest
- calendar
- docs / task systems
- MCP integrations

### 7.3. Alaya Domains

Доменная настройка:

- company
- relationship
- coaching
- personal
- recruiting

Это позволяет держать общее ядро единым, а domain semantics выносить в отдельные packs.

## 8. Что в этом может быть know-how

Know-how здесь не в одной функции, а в сочетании слоев.

Самые сильные места:

### 8.1. Event-sourced memory

Не "сохранили несколько memory records", а построили систему на raw events как source of truth.

### 8.2. Declared vs inferred state

Не каждая memory system честно различает:

- что пользователь явно сказал
- что модель только вывела

Это очень сильная инженерная и продуктовая идея.

### 8.3. Provenance + temporal updates

Система не просто хранит факт, а знает:

- когда он был получен
- из чего он был извлечен
- насколько он надежен
- не устарел ли он
- не противоречит ли он более поздним событиям

### 8.4. Memory-triggered workflows

Это, вероятно, самый важный слой.

Большинство systems сильнее в recall, чем в execution.  
Alaya может быть сильнее именно в переходе:

`memory state changed -> workflow should happen`

### 8.5. Domain portability

Если одна и та же архитектура реально хорошо работает и под company assistant, и под relationship copilot, это уже признак сильного ядра.

## 9. Конкурентное сравнение

Ниже прикладное сравнение не "кто лучше вообще", а по вопросу:

**чем Alaya может отличаться от самых заметных OSS/open-core игроков в памяти для AI.**

### 9.1. Mem0

Позиционирование:

- universal memory layer
- memory middleware для assistants и agents

Что у них сильное:

- очень понятный developer adoption story
- hosted + OSS модель
- multi-level memory
- graph memory
- хорошая упаковка как external memory infra

Что у них слабее относительно Alaya-подхода:

- меньше акцента на canonical operational state
- меньше акцента на commitments / follow-through / workflow triggering
- memory скорее как retrieval/personalization layer, чем как execution-aware state system

Текущий GitHub scale на 2026-03-27:

- примерно `51.2k stars`
- примерно `5.7k forks`

### 9.2. Letta

Позиционирование:

- platform for stateful agents
- emphasis on agent memory and persistent agent identity

Что у них сильное:

- очень сильная идея stateful agent runtime
- memory blocks / agent-centric memory model
- развитая платформа вокруг самих агентов

Что у них слабее относительно Alaya-подхода:

- логика центрирована вокруг самого агента, а не вокруг externalized operational world state
- меньше акцента на event log + provenance + domain workflows
- меньше акцента на commitments and execution loop

Текущий GitHub scale на 2026-03-27:

- примерно `21.8k stars`
- примерно `2.3k forks`

### 9.3. Graphiti / Zep

Позиционирование:

- temporal knowledge graph for AI agents
- graph-first long-term memory

Что у них сильное:

- temporal graph model
- entities and edges
- strong memory/search narrative
- хорошее попадание в graph memory wave

Что у них слабее относительно Alaya-подхода:

- основная ценность все еще в graph memory и retrieval
- operational execution layer не является центральной частью позиционирования
- commitments / reminders / workflow runtime не выглядят core value

Текущий GitHub scale на 2026-03-27:

- примерно `24.3k stars`
- примерно `2.4k forks`

### 9.4. Cognee

Позиционирование:

- knowledge engine for AI agent memory
- graph + vector memory pipeline

Что у них сильное:

- ingestion -> transformation -> graph/vector knowledge pipeline
- хорошая data-centric framing
- developer-facing simplicity

Что у них слабее относительно Alaya-подхода:

- меньше operational workflow story
- меньше акцента на commitments, state transitions и follow-through
- менее выраженная модель "memory as live execution substrate"

Текущий GitHub scale на 2026-03-27:

- примерно `14.7k stars`
- примерно `1.5k forks`

### 9.5. OpenClaw

Позиционирование:

- general-purpose agent platform / agent shell

Что у них сильное:

- коммуникационные каналы
- оболочка вокруг агента
- готовая среда для универсальных agent experiences

Что у них слабее относительно Alaya-подхода:

- memory не выглядит главным уникальным ядром
- domain-specific operational state не является центром архитектуры
- это скорее оболочка выполнения агента, чем memory and workflow substrate

### 9.6. Вывод из сравнения

Если коротко:

- `Mem0` сильнее как memory middleware
- `Letta` сильнее как stateful agent runtime
- `Graphiti` сильнее как graph-native temporal memory
- `Cognee` сильнее как knowledge pipeline
- `OpenClaw` сильнее как agent shell

Потенциальное отличие Alaya:

**операционная память, которая соединяет extraction, canonical state и workflow execution**

То есть не просто:

- remember
- search
- retrieve

А:

- ingest
- interpret
- maintain state
- detect change
- trigger action

## 10. Где может быть основной moat

Если смотреть без романтизации, то moat здесь не в том, что идею нельзя повторить.

Идею повторить можно.

Более реальный moat:

- качество abstractions
- качество ontology system
- runtime semantics workflows
- provenance and trust layer
- evals
- domain packs
- quality of developer experience
- реальные reference apps

То есть выигрывает не тот, кто первым сказал "operational memory", а тот, кто:

- сделал это понятно
- сделал это надежно
- сделал это измеримо
- сделал это полезно в нескольких доменах

## 11. Что бы я усилил в Alaya, если развивать ее в эту сторону

### 11.1. Сделать workflow triggers first-class

Не прятать их в приложении, а сделать отдельным примитивом:

- entity_created
- fact_added
- confidence_dropped
- contradiction_detected
- stale_state_detected
- deadline_approaching
- unresolved_topic_aging

### 11.2. Добавить freshness / contradiction model

Это очень важный operational слой:

- freshness score
- stale markers
- contradictory fact detection
- superseded state
- explicit uncertainty handling

### 11.3. Нормализовать ontology packs

Нужны понятные extension points:

- schema registration
- relation registration
- extraction policies
- consolidation policies
- workflow policies

### 11.4. Усилить evaluation layer

Нужно уметь мерить:

- extraction precision / recall
- commitment detection quality
- reminder usefulness
- stale-state quality
- provenance completeness

### 11.5. Сделать external integration surface

Если это должен быть core для других агентов и приложений, ему нужны:

- stable API
- MCP server
- SDK
- adapters для других runtimes

## 12. Итоговая формулировка

Если очень коротко и технично:

**Alaya это event-sourced memory runtime, который переводит разговоры и другие события в canonical state, а изменения состояния переводит в workflows и execution.**

Если чуть более продуктово:

**Alaya это operational memory and workflow engine for AI assistants.**

Самое сильное отличие этой идеи от большинства популярных memory systems:

**не просто помочь агенту помнить, а помочь агенту поддерживать состояние мира и вовремя действовать.**

## 13. Короткий TL;DR для отправки

Если нужен сверхкороткий резюме-блок для письма или сообщения:

> Alaya можно мыслить не как очередную память для LLM и не как еще один agent framework.  
> Технически это event-sourced memory runtime: raw events -> chunking -> extraction -> canonical entities/facts -> provenance -> schedules/workflows.  
> Главное потенциальное отличие от Mem0, Letta, Graphiti, Cognee и похожих систем в том, что Alaya может быть не просто memory/retrieval слоем, а operational memory engine: система, которая не только знает, что произошло, но и умеет запускать follow-ups, reminders и другие workflows от изменений в состоянии памяти.
