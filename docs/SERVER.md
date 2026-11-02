# Сервер SmartTrip

Развёртывание: 25 октября 2026 года. Ubuntu 24.04, 1 vCPU, 2 GB RAM.

Бот перенесён из локальной папки `Downloads/SmartTrip_MVP 2`.
Рабочая папка сервера: `/opt/smarttrip`.
Процесс работает от системного пользователя `smarttrip`, не от root.
Настройки: `/opt/smarttrip/.env`, доступ root и группе smarttrip.
База поездок: `/opt/smarttrip/runtime/smarttrip.sqlite3`.
Служба systemd: `smarttrip.service`, автозапуск и перезапуск при завершении процесса.

## Управление

На Mac подключиться:

```bash
ssh root@SERVER_IP
```

Затем на сервере:

```bash
systemctl status smarttrip --no-pager
systemctl restart smarttrip
journalctl -u smarttrip -n 50 --no-pager
```

Остановить службу:

```bash
systemctl stop smarttrip
```

Изменить настройки, затем перезапустить:

```bash
nano /opt/smarttrip/.env
systemctl restart smarttrip
```

Не запускайте на Mac второй экземпляр с тем же токеном, пока работает серверная служба.
Для параллельной разработки используйте отдельных тестовых ботов.
Не публикуйте `.env`, базу поездок и резервные копии на GitHub.
Автоматическое резервное копирование пока не настроено.

Пароли сервера и API-ключи в этом документе не сохраняются.
