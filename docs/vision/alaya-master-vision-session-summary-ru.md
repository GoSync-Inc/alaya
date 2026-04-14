# Alaya / Between / Core — master vision и summary всей сессии

Черновик master document  
Язык: русский  
Статус: internal working synthesis  
Назначение: единый артефакт для передачи в реализацию, обсуждения и последующего уточнения

## 1. Зачем нужен этот документ

За серию обсуждений сформировался не один вывод, а целая связанная картина:

- как понимать Alaya
- почему memory сама по себе недостаточна
- зачем нужны entities, facts, workflows и execution
- чем `Between` связан с `AlayaOS`
- почему идея shared core одновременно привлекательна и опасна
- где в этом всем может быть настоящий know-how
- как отличаться от memory-first и agent-shell-first игроков
- когда стоит думать о core, а когда нет

Проблема в том, что эти мысли уже распределены по нескольким отдельным заметкам и большому количеству диалога.  
Нужен единый документ, который:

- собирает всю линию целиком
- понятен без знания полного контекста разговора
- пригоден как рабочий reference для кодовой реализации

## 2. Короткий итог

Самая сильная итоговая рамка выглядит так:

**Alaya — это не просто memory layer и не просто агентный продукт.  
В сильной версии это operational memory and workflow engine for AI assistants.**

По-русски:

**Операционная память и движок workflows для AI-ассистентов.**

Сверхкороткая формула:

**Из разговоров в состояние. Из состояния в действия.**

Именно эта формула оказалась наиболее устойчивой во всех обсуждениях.

## 3. Как мы к этому пришли

### Шаг 1. Разговор про “память”

Отталкивались от внешних memory systems и memory infra, в частности:

- Mem0
- Letta / MemGPT
- Graphiti / Zep
- Cognee
- Supermemory
- OpenClaw

Сначала вопрос звучал примерно так:

- нужна ли вообще внешняя память
- что не помещается в большие context windows
- когда оправдано отдельное memory layer

### Шаг 2. Сдвиг от “памяти” к “модели мира”

По мере разговора выяснилось, что для Alaya и похожих систем проблема не сводится к long context.

Главный вопрос стал звучать так:

- как из хаотичных сырых данных собирать рабочую модель мира
- как представлять сущности, статусы, решения, обязательства, блокеры, цели
- как не заставлять LLM каждый раз строить все это заново on demand

Из этого появился важный сдвиг:

**в operational systems память почти всегда оказывается не просто storage problem, а world model problem**

### Шаг 3. Сдвиг от world model к operational loop

Дальше стало ясно, что даже world model сама по себе — не конец истории.

Для реальной ценности нужны:

- reminders
- delayed tasks
- recurring jobs
- follow-ups
- stale detection
- review loops
- workflows, запускающиеся от изменений состояния

Это и перевело разговор из “memory architecture” в “operational memory”.

### Шаг 4. Появление идеи shared core

Когда стало понятно, что `Between` может использовать очень похожую архитектурную линию, возник вопрос:

- может ли существующее ядро Alaya стать shared core
- стоит ли его когда-то выделять
- нужно ли думать про open source/open-core

Дальнейшие обсуждения показали, что shared core — сильная гипотеза, но пока не доказанный факт.

## 4. Что именно мы теперь считаем проблемой

Речь идет не о “бесконечной памяти” и не о “хранении большего количества текста”.

Настоящая проблема формулируется так:

**как превращать поток сырых событий из множества источников в рабочее, проверяемое, обновляемое состояние мира, на котором можно строить надежные действия**

Это включает в себя:

- ingest
- extraction
- entity resolution
- temporal updates
- provenance
- forgetting / superseding
- stale detection
- workflow triggering

## 5. Архитектурная гипотеза

### 5.1. Четыре слоя

Наиболее устойчивая схема, к которой мы пришли:

1. `Events`
- сообщения
- транскрипты
- аудио
- summaries
- документы
- calendar/task updates
- integration events

2. `Memory`
- entities
- facts
- relations
- commitments
- preferences
- goals
- dates
- unresolved topics

3. `Reasoning`
- extraction
- matching
- normalization
- consolidation
- contradiction handling
- ranking / prioritization

4. `Action Loop`
- reminders
- delayed jobs
- recurring jobs
- workflows
- reviews
- follow-ups
- recovery

### 5.2. Ключевая формула

Не:

- сохранить память
- найти похожий кусок
- подставить его в prompt

А:

- принять событие
- изменить state
- понять, важно ли это
- при необходимости запустить действие

## 6. Почему обычной memory architecture мало

Memory-only подходи часто делают одну из трех вещей:

- хранят историю сообщений
- кладут все в vector search
- сохраняют отдельные facts/preferences

Этого недостаточно, если система должна:

- отслеживать обязательства
- понимать, что информация устарела
- различать факт и гипотезу
- видеть конфликт между старым и новым
- запускать workflow по изменению state
- уважать ACL
- уметь показать provenance

Поэтому в нашем понимании:

**операционная память = память + state model + execution semantics**

## 7. L0 / L1 / L2 / execution

### 7.1. L0 — raw event log

Сырые события как source of truth.

Что важно:

- ничего не терять
- хранить source metadata
- хранить ACL / visibility
- хранить raw text/payload
- иметь deduplication

Это не optional.

### 7.2. L0.5 — chunking и gating

Нужен промежуточный слой:

- segment the data
- выделить смысловые куски
- ранжировать важность
- domain classification before extraction

Это снижает стоимость и шум.

### 7.3. L1 — canonical entities

Один из важнейших выводов сессии:

**для Alaya-подхода L1 не опционален**

Причины:

- нужен устойчивый слой объектов мира
- нужен entity resolution
- нужны state transitions
- нужен lifecycle
- нужны workflows поверх состояния, а не текста

Это может быть просто реализовано:

- PostgreSQL
- typed JSON fields
- relation tables

То есть graph DB не обязателен, но L1 как слой обязателен.

### 7.4. L2 — facts и state transitions

Здесь живет рабочее знание:

- declared facts
- inferred facts
- stale facts
- contradicted facts
- superseded facts

### 7.5. Execution layer

Напоминания и jobs — это не сервис “рядом”, а часть самой архитектуры.

Нужны:

- delayed jobs
- recurring schedules
- idempotency
- recovery cron
- retries
- fan-out
- memory-triggered workflows

Именно этот слой переводит memory system в operational system.

## 8. Declared vs inferred

Это один из самых сильных архитектурных принципов, которые зафиксировались в обсуждении.

Нужно различать:

- `declared` — что человек явно сказал
- `inferred` — что модель вывела из наблюдений

Причины:

- честность системы
- better debugging
- меньше ложной уверенности
- лучше correction loop
- лучше provenance

## 9. Provenance и доверие

Каждый важный вывод должен быть связан с источником.

Система должна уметь ответить:

- откуда взят факт
- из каких событий он получен
- когда он был выведен
- насколько он надежен

Без provenance memory превращается в black box.  
С provenance она становится пригодной для operational use.

## 10. Память против модели мира

Один из сильных поворотов обсуждения был таким:

**проектируя память, мы часто на деле проектируем модель мира**

То есть разговор про memory — это во многом разговор про:

- ontology
- abstractions
- state semantics
- lifecycle

При этом в дискуссии возникла важная контрпозиция:

- слишком opinionated schema может вносить bias
- сильная модель иногда может построить representation сама

Итоговый synthesis:

**не raw-only и не hand-crafted-only**

А:

- raw layer как source of truth
- learned extraction layer
- explicit operational model поверх этого

То есть:

**hand-crafted operational frame over learned interpretation**

## 11. Что мы думаем про graph / vector / files

### 11.1. Files-only подход

Полезен как baseline для персонального агента.  
Недостаточен для operational system.

### 11.2. Vector-only memory

Полезна для retrieval.  
Недостаточна для temporal truth, contradictions, state transitions и workflows.

### 11.3. Graph-first memory

Полезна для relation-heavy reasoning.  
Опасна, если превращается в слишком тяжелую основу без доказанной пользы.

### 11.4. Наш pragmatic conclusion

- simple source of truth
- explicit state layer
- vector retrieval as a supporting layer
- graph as optional derived layer
- evals deciding complexity

## 12. Что Alaya уже показывает

По текущему состоянию Alaya, включая недавние обновления, видно, что система уже движется в platform-capable сторону:

- Platform API
- MCP server
- scheduling
- webhooks
- observability
- extraction pipeline
- L1 / consolidation thinking

Это значит:

- идея core перестает быть чисто теоретической
- но это не означает, что core уже надо прямо сейчас вырезать в отдельную платформу

## 13. Что мы поняли про конкурентов

### Memory / context infra

- Mem0
- Letta
- Graphiti / Zep
- Cognee
- Supermemory

### Adjacent commercial products

- Glean
- Dust
- Lindy
- Granola

### Вывод

Никто из них в явном виде не владеет категорией:

**operational memory + workflow execution**

У многих сильны:

- retrieval
- memory infra
- stateful agents
- graph memory
- workflow shells

Но у Alaya есть шанс отличаться именно в связке:

**events -> state -> workflows**

## 14. Что мы поняли про open source

### Неочевидная правда

Open source в этой категории реально работает как distribution.

Но:

- stars не равны revenue
- OSS не решает проблему packaging
- не надо открывать сырой core только потому, что это тренд

### Рабочий вывод

Если когда-то идти в open-core/open-source, то открывать стоит не продукт целиком, а зрелое ядро.

Но это не ближайшая цель.

## 15. Что мы поняли про shared core

Самая важная practical развилка:

- если ждать идеальный shared core, `Between` можно задержать надолго
- если начать `Between` раньше, придется принять временное дублирование

Итоговый вывод:

**не надо ждать идеального core, чтобы начать Between**

Но:

- shared core пока считать гипотезой
- внимательно собирать доказательства reuse
- не делать premature platform rewrite

## 16. Практическая стратегия

### 16.1. AlayaOS

- продолжать допиливать продукт
- стабилизировать extraction
- держать discipline around boundaries

### 16.2. Between

- можно начинать раньше
- использовать сильные части Alaya DNA
- не притворяться, что это уже shared platform

### 16.3. Core

- пока internal architectural hypothesis
- не делать big-bang extraction
- refactor in place where possible
- вести reuse evidence

## 17. Как не делать carve-out

Плохой путь:

- вырезать кусок из AlayaOS
- отдельно перепилить его в “идеальный core”
- потом пытаться встроить обратно

Это почти гарантированный двойной рефакторинг и боль.

Лучший путь:

- refactor in place
- помечать seams
- выделять generic interfaces постепенно
- дать двум продуктам доказать, что shared layer реален

## 18. Что считать core candidates

Потенциальные кандидаты:

- event log
- ingestion metadata
- ACL / visibility model
- chunking / domain gating
- extraction contracts
- entity / fact / relation primitives
- provenance
- declared vs inferred state semantics
- stale / contradicted / superseded handling
- schedules
- workflow triggers
- execution policies
- API / MCP surface

## 19. Что точно не core

- company-specific ontology
- relationship-specific ontology
- Slack-specific UX
- Telegram-specific UX
- company-specific workflows
- relationship-specific workflows
- product packaging
- pricing
- top-level app behavior

## 20. Что обязательно нужно мерить

Один из самых сильных выводов из разговоров про memory systems:

**без evals все это быстро превращается во вкусовщину**

Нужно мерить:

- extraction precision / recall
- reminder usefulness
- commitment detection quality
- stale-state quality
- provenance completeness
- contradiction handling
- workflow relevance

## 21. Где может быть know-how

Не в одной магической функции.

А в композиции:

- event-sourced memory
- typed extraction
- canonical state
- declared vs inferred
- provenance
- temporal updates
- consolidation
- workflow triggering от state changes

Повторить идею можно.  
Сложно быстро и качественно повторить всю систему целиком.

## 22. Что особенно важно для реализации прямо сейчас

### 22.1. Не плодить ненужную доменную сцепку

В новом коде все время задавать вопрос:

- это core?
- это domain?
- это app shell?

### 22.2. Не переобобщать раньше времени

Если abstraction придумана без второго реального use case, относиться к ней с подозрением.

### 22.3. Беречь raw truth

Raw events нельзя терять и нельзя превращать в derived-only систему.

### 22.4. Беречь ACL

ACL — потенциально один из самых недооцененных differentiators, особенно если propagation идет через:

- ingest
- extraction
- memory
- retrieval
- workflows

### 22.5. Не забывать про execution

Память без execution = полезный, но неполный слой.  
Для Alaya execution — часть identity.

## 23. Практические правила для команд и Codex

Этот блок специально нужен для внедрения во время параллельной реализации других задач.

### При проектировании новой функции

- сначала определить, это event / memory / reasoning / workflow / app shell
- если это stateful behavior, задать вопрос, где будет жить источник истины
- если это derived knowledge, зафиксировать provenance
- если это inference, не путать с declared truth
- если это workflow, определить trigger, policy, retry, idempotency, ACL

### При добавлении нового domain logic

- сначала решить, это реально новый reusable primitive или domain rule
- если rule доменная — не тащить ее в generic layer

### При добавлении новых integrations

- думать сначала про event ingestion contract, а не про красивый продуктовый use case

### При добавлении новых memory layers

- спрашивать: это source of truth, derived layer или optimization?

## 24. Рабочая структура артефактов из этой сессии

В рамках текущей работы уже созданы:

- white paper про operational memory
- технический аппендикс
- future artifacts / strategy note

Этот document является master synthesis поверх них.

## 25. Главные решения, зафиксированные по итогам сессии

1. `Alaya` лучше мыслить как `operational memory and workflow engine`, а не просто memory layer.
2. `L1 entities` для такого подхода не optional.
3. Graph DB optional; canonical state layer mandatory.
4. Vector retrieval полезен, но не является достаточным фундаментом.
5. Execution layer — часть identity системы.
6. Shared core сейчас — гипотеза, а не доказанный продукт.
7. Не стоит тормозить `Between` ожиданием идеального core.
8. Не стоит делать big-bang carve-out.
9. Нужно вести reuse evidence и `Core Extraction Journal`.
10. Evals обязательны.

## 26. Рабочий тезис на будущее

Если в одной фразе передавать самую важную мысль из всей сессии:

**Alaya — это попытка построить не память для LLM, а систему, которая из потока событий собирает модель мира и умеет действовать по изменениям этой модели.**

Именно эта формулировка на текущий момент лучше всего собирает воедино:

- memory
- intelligence
- extraction
- world model
- workflows
- Between
- AlayaOS
- и потенциальный будущий core

## 27. Что делать дальше

### В ближайшее время

- использовать этот документ как reference during implementation
- не раздувать premature abstractions
- держать shared-core thinking в голове, но не превращать его в отдельный проект раньше времени

### В среднесрочной перспективе

- смотреть, что реально переиспользуется между `AlayaOS` и `Between`
- стабилизировать extraction и workflow semantics
- готовить internal convergence только когда появятся факты, а не интуиции

### В долгосрочной перспективе

Если overlap подтвердится:

- оформить internal shared core
- и только потом решать, нужен ли ему отдельный repo, external API focus или open-source trajectory

## 28. Финальная формула

**Не строить платформу в надежде, что продукты потом под нее подстроятся.  
Сначала дать продуктам доказать, что общий engine им действительно нужен.**

Это самый трезвый и самый полезный итог всей сессии.
