# Модель базы данных — AI Auto Applier

## Таблица: User (Пользователь)
| Поле          | Тип данных         | Описание                              | Примечания                       |
|---------------|--------------------|-------------------------------------|---------------------------------|
| id            | UUID / SERIAL      | Уникальный идентификатор пользователя | PRIMARY KEY                     |
| name          | VARCHAR(100)       | Имя пользователя                    |                                 |
| email         | VARCHAR(255)       | Email пользователя                  | UNIQUE, для логина              |
| password_hash | VARCHAR(255)       | Хэш пароля                         | Если планируется авторизация    |
| created_at    | TIMESTAMP          | Дата и время создания записи       | DEFAULT CURRENT_TIMESTAMP       |
| updated_at    | TIMESTAMP          | Дата и время последнего обновления |                                 |

---

## Таблица: FilterSettings (Настройки фильтров)
| Поле          | Тип данных         | Описание                              | Примечания                       |
|---------------|--------------------|-------------------------------------|---------------------------------|
| id            | UUID / SERIAL      | Уникальный идентификатор            | PRIMARY KEY                     |
| user_id       | UUID / INTEGER     | Ссылка на пользователя              | FOREIGN KEY -> User(id)         |
| city          | VARCHAR(100)       | Город поиска вакансий               |                                 |
| salary_min    | INTEGER            | Минимальная зарплата                |                                 |
| salary_max    | INTEGER            | Максимальная зарплата               |                                 |
| keywords      | TEXT               | Ключевые слова для поиска           | Можно хранить в JSON            |
| created_at    | TIMESTAMP          | Дата создания                      | DEFAULT CURRENT_TIMESTAMP       |
| updated_at    | TIMESTAMP          | Дата обновления                    |                                 |

---

## Таблица: Vacancy (Вакансия)
| Поле          | Тип данных         | Описание                              | Примечания                       |
|---------------|--------------------|-------------------------------------|---------------------------------|
| id            | UUID / SERIAL      | Внутренний ID вакансии               | PRIMARY KEY                     |
| hh_vacancy_id | VARCHAR(50)        | ID вакансии из hh.ru API             | Для связи с внешним API         |
| user_id       | UUID / INTEGER     | Владелец вакансии (соискатель)      | FOREIGN KEY -> User(id)         |
| title         | VARCHAR(255)       | Название вакансии                   |                                 |
| company       | VARCHAR(255)       | Компания                           |                                 |
| description   | TEXT               | Описание вакансии                   |                                 |
| url           | VARCHAR(500)       | Ссылка на вакансию                  |                                 |
| published_at  | TIMESTAMP          | Дата публикации вакансии            |                                 |
| fetched_at    | TIMESTAMP          | Дата и время получения вакансии     |                                 |

---

## Таблица: Application (Отклик)
| Поле               | Тип данных         | Описание                              | Примечания                       |
|--------------------|--------------------|-------------------------------------|---------------------------------|
| id                 | UUID / SERIAL      | Уникальный идентификатор отклика     | PRIMARY KEY                     |
| vacancy_id         | UUID / INTEGER     | Вакансия                            | FOREIGN KEY -> Vacancy(id)      |
| user_id            | UUID / INTEGER     | Пользователь, отправивший отклик    | FOREIGN KEY -> User(id)         |
| applied_at         | TIMESTAMP          | Дата и время отклика                | DEFAULT CURRENT_TIMESTAMP       |
| status             | VARCHAR(50)        | Статус отклика (отправлен, ошибка) |                                 |
| cover_letter       | TEXT               | Текст сопроводительного письма      |                                 |

---

## Таблица: Log (Логи)
| Поле          | Тип данных         | Описание                              | Примечания                       |
|---------------|--------------------|-------------------------------------|---------------------------------|
| id            | UUID / SERIAL      | Уникальный идентификатор записи лога | PRIMARY KEY                     |
| user_id       | UUID / INTEGER     | Пользователь                        | FOREIGN KEY -> User(id)         |
| action        | VARCHAR(255)       | Действие (например, "отклик отправлен") |                             |
| description   | TEXT               | Детали действия или ошибки          |                                 |
| created_at    | TIMESTAMP          | Дата и время записи                 | DEFAULT CURRENT_TIMESTAMP       |
