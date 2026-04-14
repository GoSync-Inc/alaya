# Alaya / Between — implementation note для команды

Черновик инженерной версии  
Язык: русский  
Назначение: рабочая записка для команд, которые уже постепенно закладывают подход в реализацию

## 1. Цель документа

Этот документ нужен не как vision deck, а как практическая инженерная рамка.

Его задача:

- зафиксировать, что именно мы считаем базовой архитектурной линией
- уменьшить вероятность случайного сползания в inconsistent design
- дать командам простой reference при реализации соседних задач

## 2. Рабочая формулировка

Используем следующую рамку:

**Alaya — operational memory and workflow engine for AI assistants**

Внутренний смысл этой формулировки:

- память не сводится к retrieval
- core ценность не в хранении текста, а в поддержании состояния мира
- workflows и execution — часть identity системы, а не периферийная интеграция

## 3. Что считается source of truth

### Обязательный слой: L0 raw events

Все входящие данные должны существовать как raw event layer.

Примеры:

- message
- transcript
- meeting summary
- voice transcript
- integration update
- calendar/task/document event

Для каждого event важны:

- source type
- source id
- source timestamp
- actor
- raw payload / raw text
- access metadata / ACL
- dedup / content hash

### Почему это важно

- воспроизводимость
- provenance
- reprocessing
- безопасная эволюция extraction pipeline
- защита от premature schema lock-in

## 4. Что считается обязательным derived layer

### L0.5: chunking + domain gating

Нужен промежуточный слой между raw data и extraction.

Функции:

- смысловое разбиение
- cheap classification
- importance filtering
- domain routing

Цель:

- не гонять весь шум в дорогой extraction
- снизить токены
- отделять small talk и low-signal content от operationally relevant content

### L1: canonical entities

L1 не считаем optional для Alaya-подхода.

L1 нужен для:

- устойчивых объектов мира
- entity resolution
- state transitions
- ACL propagation
- workflow triggering
- temporal lifecycle

На практике L1 может быть реализован без сложной graph-native системы.

Минимально достаточно:

- PostgreSQL
- typed entities
- relation tables
- versioning
- provenance links

### L2: facts and state transitions

На этом слое фиксируются:

- declared facts
- inferred facts
- stale facts
- contradicted facts
- superseded facts

Цель не просто “запомнить факт”, а вести рабочее состояние объекта во времени.

## 5. Execution как first-class layer

Execution в этой архитектуре не auxiliary service, а core subsystem.

Нужны как минимум:

- delayed jobs
- recurring jobs
- retries
- idempotency
- recovery cron
- workflow triggers
- action policies

Примеры:

- new agreement -> schedule follow-up
- deadline approaching -> enqueue reminder
- stale state detected -> surface in review
- unresolved topic aging -> create check-in item
- user correction -> rerun downstream recalculation

## 6. Обязательные архитектурные принципы

### 6.1. Declared vs inferred

Нельзя смешивать:

- что пользователь явно сказал
- что система вывела из контекста

Это должно сохраняться в модели явно.

### 6.2. Provenance

Каждый важный derived artifact должен быть привязан к исходным raw events.

### 6.3. ACL propagation

ACL нельзя оставлять только на уровне raw storage.

Оно должно участвовать в:

- extraction
- memory updates
- retrieval
- workflows

### 6.4. Staleness / contradiction / supersession

Система должна уметь различать:

- актуальное
- устаревшее
- противоречивое
- вытесненное более поздним state

### 6.5. Evals over intuition

Сложность memory architecture нельзя оправдывать эстетически.

Любой сложный слой должен быть подтвержден evals или operational benefit.

## 7. Что считать core, а что domain

### `core`

- events
- chunking/gating
- extraction contracts
- entities/facts/relations primitives
- provenance
- stale/contradiction semantics
- schedules
- workflow triggers
- execution policies
- API / MCP surface

### `domain`

- company ontology
- relationship ontology
- prompts
- domain workflow rules
- app UX
- app packaging

## 8. Как мыслить `AlayaOS`, `Between` и `Core`

На текущем этапе используем следующую рамку:

- `AlayaOS` — текущий продукт
- `Between` — новый vertical
- `Alaya Core` — пока внутренняя гипотеза о shared engine

Важно:

- `Core` пока не считать отдельным продуктом
- не строить его в вакууме
- доказывать через реальное reuse

## 9. Практическое решение по разработке

### Не делать сейчас

- big-bang carve-out
- отдельный public repo под core
- massive rewrite ради идеальной modularity
- premature universal abstractions

### Делать сейчас

- продолжать развивать `AlayaOS`
- не задерживать `Between` ожиданием идеального core
- собирать reusable seams
- фиксировать divergence points
- вести `Core Extraction Journal`

## 10. Core Extraction Journal

Для каждой крупной фичи или модуля фиксировать:

- где используется сейчас
- нужен ли в `Between`
- reusable / reusable with changes / domain-only
- какие зависимости мешают переиспользованию
- какая цена выделения

Цель:

- принимать решения на evidence
- а не на ощущении “кажется, это было общим”

## 11. Когда shared core можно считать зрелой гипотезой

Нужны признаки:

- extraction pipeline концептуально стабилен
- API / MCP surface уже не плавает хаотично
- overlap между `AlayaOS` и `Between` подтвержден в коде
- workflows имеют общие primitives
- выгода от shared core выше, чем цена refactor

Если этих признаков нет, core пока остается только внутренней архитектурной гипотезой.

## 12. Что проверять во время реализации

### При добавлении новой интеграции

- сначала думать про event contract
- потом про extraction implications
- потом про ACL

### При добавлении новой extraction logic

- где живет raw truth
- что declared, что inferred
- куда пишется provenance
- нужен ли consolidation step

### При добавлении workflow

- какой trigger
- какая policy
- какой retry/idempotency contract
- какой ACL boundary
- что считается successful completion

### При добавлении новой сущности

- это reusable primitive или domain-specific artifact
- нужен ли lifecycle
- нужны ли status transitions
- как она забывается / устаревает / заменяется

## 13. Временный technical stack baseline

Текущий baseline, который соответствует выбранной линии:

- `Python`
- `FastAPI`
- `PostgreSQL`
- `pgvector`
- `Redis`
- `TaskIQ`
- optional graph layer if justified
- provider abstraction for LLM/extraction
- API + MCP as external surfaces

Графовый слой считать optional optimization, а не обязательным фундаментом.

## 14. Как оценивать новые memory ideas

При появлении новой модной memory/system идеи задавать 5 вопросов:

1. Это source of truth или derived layer?
2. Это уменьшает шум или просто усложняет архитектуру?
3. Это улучшает workflows/execution или только retrieval?
4. Это измеримо через evals?
5. Это помогает двум доменам или только одному?

Если ответов нет, слой пока не вводить.

## 15. Короткий implementation doctrine

Если свести все к нескольким правилам:

- raw data must survive
- extraction must be explainable
- entities must be stable
- inferred must not masquerade as declared
- workflows must respect state, ACL and provenance
- evals decide complexity
- shared core must be proven by reuse, not assumed

## 16. Главный инженерный вывод

Не строить “memory platform ради memory platform”.

Строить систему, где:

- события превращаются в состояние
- состояние меняется во времени
- изменения состояния запускают полезные действия

Это и есть рабочая инженерная интерпретация всей нашей общей линии.
