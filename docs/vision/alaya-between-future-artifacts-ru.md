# Alaya / Core / Between — полезные артефакты на будущее

Черновик стратегического рабочего документа  
Язык: русский  
Статус: internal working draft

## Зачем нужен этот документ

Вокруг Alaya, потенциального shared core и продукта Between есть сразу несколько направлений:

- продолжать развивать `AlayaOS` как продукт
- думать про будущий `Alaya Core`
- возможно когда-то идти в сторону open-source/open-core
- параллельно не потерять скорость запуска `Between`

Проблема не в нехватке идей, а в том, что их легко перепутать и начать одновременно строить:

- продукт
- платформу
- open-source историю
- новый vertical

Этот документ нужен как набор рабочих артефактов и опорных решений, чтобы не принимать одни и те же решения заново каждые две недели.

## Главная рабочая рамка

Пока разумно мыслить систему так:

- `AlayaOS` — текущий продукт
- `Between` — новый vertical
- `Alaya Core` — пока гипотеза о будущем shared engine

Важно:

**Alaya Core пока не должен считаться отдельным продуктом.**

Сначала он должен доказать, что:

- реально нужен двум доменам
- не является красивой абстракцией без пользы
- позволяет ускорить разработку, а не только усложнить ее

## Артефакт 1. Working Thesis

### Текущая формулировка

`Alaya` можно мыслить как:

**Operational Memory and Workflow Engine for AI Assistants**

По-русски:

**Операционная память и движок workflows для AI-ассистентов**

Короткая формула:

**Из разговоров в состояние. Из состояния в действия.**

### Зачем это нужно

Эта формулировка полезна не как маркетинг, а как способ проверять решения:

- это часть памяти или приложения
- это generic execution layer или доменная логика
- это reusable workflow primitive или одноразовая фича

## Артефакт 2. Что считать core, а что нет

### Кандидаты в `core`

Это то, что потенциально может жить и под `AlayaOS`, и под `Between`:

- raw event log
- deduplication / ingestion metadata
- chunking / gating
- extraction interfaces
- canonical entities / facts / relations primitives
- provenance model
- declared vs inferred state model
- stale / contradicted / superseded state semantics
- retrieval interfaces
- schedules
- delayed tasks
- recurring workflows
- workflow triggers
- execution policies
- API / MCP surface

### Не `core`

Это то, что почти наверняка должно оставаться domain-specific:

- company-specific ontology
- relationship-specific ontology
- Slack-first UX decisions
- Telegram-specific conversational UX
- CEO briefings
- relationship reviews
- domain prompts
- domain-specific workflow rules
- pricing / billing / product packaging

## Артефакт 3. Решение на ближайшее время

### Базовое решение

Не делать сейчас большой carve-out в отдельную платформу.

### Почему

Потому что сейчас:

- extraction еще стабилизируется
- abstractions еще двигаются
- `Between` хочется запускать быстрее, а не после долгого platform refactor

### Практический вывод

На ближайший период стратегия такая:

- `AlayaOS` развивается дальше
- `Between` можно начинать раньше, не дожидаясь идеального shared core
- `shared core` пока считать внутренней архитектурной гипотезой

## Артефакт 4. Operating model на ближайшие месяцы

### Режим работы

Нужна двухскоростная стратегия.

#### Трек 1. Product speed

- не тормозить запуск `Between`
- использовать сильные куски Alaya-подхода уже сейчас
- не пытаться сразу сделать “универсальную платформу”

#### Трек 2. Architecture discipline

Пока идет разработка, помечать:

- что реально reusable
- что явно company-specific
- что явно relationship-specific
- какие зависимости мешают convergence
- где naming слишком доменное

Это снижает будущую боль.

## Артефакт 5. Core Extraction Journal

Нужен живой журнал, куда складываются наблюдения по мере работы.

### Формат записи

Для каждого крупного куска:

- модуль / фича
- используется ли в `AlayaOS`
- нужен ли в `Between`
- reusable without changes / reusable with changes / domain-only
- какие зависимости мешают переиспользованию
- что пришлось бы абстрагировать
- насколько больно было бы это вынести

### Зачем

Чтобы потом не спорить “кажется, это было общим”, а иметь факты.

## Артефакт 6. Convergence Decision Gate

Перед тем как реально выделять `Alaya Core`, должны быть положительные сигналы по нескольким критериям.

### Сигналы готовности

- extraction pipeline стабилен концептуально
- API / MCP surface перестал резко меняться
- есть минимум два домена, которым реально нужен общий слой
- overlap между `AlayaOS` и `Between` не меньше условно 60-70% по core pieces
- workflows имеют понятные generic primitives
- выгода от shared core выше, чем цена refactor

### Сигналы неготовности

- abstractions пока придумываются в вакууме
- `Between` требует очень другой memory model
- scheduler/workflow semantics еще плавают
- domain logic все еще глубоко прошита в generic слои

## Артефакт 7. Временная стратегия для `Between`

### Что можно делать

- стартовать `Between` на форке / ответвлении / вертикальном срезе Alaya-подхода
- брать сильные существующие идеи: events, memory pipeline, workflows, schedules
- сознательно допускать временное дублирование

### Чего не надо делать

- не обещать себе, что это уже shared core
- не тратить недели на premature generalization
- не переписывать `AlayaOS` ради абстракций, которые пока ничем не доказаны

### Ключевой принцип

`Between` нужен не только как продукт, но и как реальный тест на переносимость архитектуры.

## Артефакт 8. Возможная структура будущего shared engine

Если shared layer когда-то созреет, он, вероятно, должен иметь такую форму.

### `core/`

- events
- ingestion
- chunking
- extraction contracts
- facts
- entities
- relations
- provenance
- retrieval
- schedules
- workflow triggers
- execution policies
- API / MCP

### `domains/company/`

- person
- team
- task
- project
- decision
- goal
- company-specific prompts and policies

### `domains/relationship/`

- relationship
- agreement
- followup
- important_date
- tension
- preference
- unresolved_topic
- date_plan

### `apps/alayaos/`

- product shell
- company UX
- company workflows

### `apps/between/`

- product shell
- relationship UX
- relationship workflows

Важно:

Это не значит, что нужно прямо сейчас все раскладывать по этим папкам.  
Это значит, что это хорошая целевая форма, если shared layer окажется настоящим.

## Артефакт 9. Что проверять на реальных кейсах

Чтобы понимать, есть ли смысл в shared core, нужны не рассуждения, а реальные проверки.

### Проверка 1. Shared ingest

Одинаково ли хорошо raw event model ложится на:

- Slack / company data
- Telegram / relationship data
- transcripts / voice summaries

### Проверка 2. Shared memory semantics

Одинаково ли полезны:

- facts
- relations
- provenance
- declared vs inferred
- stale state
- contradiction handling

в обоих доменах.

### Проверка 3. Shared workflow runtime

Может ли один и тот же execution layer обслуживать:

- company reminders
- reviews
- standups / summaries
- relationship follow-ups
- important date reminders
- unresolved topic reviews

### Проверка 4. ACL model

Это критично.

Нужно проверить, выдерживает ли одна модель доступа:

- workspace / team / DM / private channel
- personal / couple / private memory / shared memory

Если нет — shared core придется делать более гибким в security model.

## Артефакт 10. Главные риски

### Риск 1. Ранняя платформизация

Опасность:

- сделать красивую платформу, которая не нужна продуктам

### Риск 2. Двойной рефакторинг

Опасность:

- сначала вынести криво
- потом перепилить отдельно
- потом мучительно встраивать обратно

### Риск 3. Слишком разные домены

Опасность:

- company и relationship окажутся похожи только на словах

### Риск 4. Потеря скорости

Опасность:

- строить core и задержать запуск `Between`

### Риск 5. Ложная универсальность

Опасность:

- принимать one-off abstractions за будущую платформу

## Артефакт 11. Что точно стоит делать уже сейчас

- вести `Core Extraction Journal`
- при новых изменениях задавать вопрос: core это или domain
- не плодить новые жестко company-specific зависимости в generic слоях
- фиксировать reusable workflow primitives
- сохранять discipline around provenance, ACL и state transitions
- не принимать repo split как обязательную ближайшую цель

## Артефакт 12. Что пока не стоит делать

- отдельный public repo под core
- публичный stable SDK
- обещать external developer platform
- большой rename ради красоты
- massive abstraction pass до появления второго живого потребителя

## Артефакт 13. Возможный вопросник для будущих решений

Перед каждым крупным архитектурным шагом полезно задавать себе одни и те же вопросы:

- это помогает продукту или только архитектурной красоте
- это reusable в двух доменах или только в одном
- это уменьшает future pain или создает новый слой сложности
- это сейчас bottleneck или просто интересная идея
- что будет, если пока оставить это duplicated
- что будет, если слишком рано обобщить

## Артефакт 14. Короткое резюме для себя

### Что сейчас правда

- `AlayaOS` — реальный продукт
- `Between` — реальный будущий vertical
- `Alaya Core` — пока гипотеза

### Что делать сейчас

- не тормозить `Between` ожиданием идеального core
- не делать premature platform rewrite
- развивать `AlayaOS` и запускать `Between`
- параллельно собирать доказательства того, что shared layer действительно существует

### Что делать потом

Если overlap подтвердится на практике:

- делать internal shared core
- и только потом решать, нужен ли отдельный repo, external API focus или open-source story

## Итог

Главная полезная установка на будущее:

**Не строить платформу в надежде, что продукты потом под нее подстроятся.  
Сначала дать двум продуктам доказать, что общий engine им правда нужен.**

Это более медленный путь с точки зрения красивой архитектуры, но более надежный путь с точки зрения реальности.
