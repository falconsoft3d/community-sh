"""Odoo databases of an instance: create one, its administrator password, and making a copy safe (neutralize, demos). Part of DockerService."""
import re
from ..task_log import progress
from .docker_helpers import (
    odoo_command,
    odoo_major,
    odoo_password_hash,
)


class DatabaseMixin:
    def create_database(self, instance, name, password, lang='', demo=False):
        """
        A new Odoo database in the instance (`odoo -d name -i base`), without demo data unless asked, and
        with this password for its administrator. Returns the administrator's login.
        """
        from ..permissions import DATABASE_NAME_RE
        if not DATABASE_NAME_RE.match(name or ''):
            raise ValueError('Nombre de base de datos no válido')
        if lang and not re.fullmatch(r'[a-z]{2,3}(_[A-Z]{2})?(@[a-z]+)?', lang):
            raise ValueError('Idioma no válido (por ejemplo es_ES)')
        odoo_container = self._get_container(f'odoo_{instance.name}')
        db_container = self._start_db_container(instance)
        if odoo_container is None or db_container is None:
            raise Exception('La instancia no está desplegada: despliégala antes de crear una base de datos')
        self._wait_for_postgres(db_container)
        if name in self._list_user_databases(db_container):
            raise Exception(f'La base de datos {name} ya existe')
        progress(15, f'Creando la base de datos {name}')
        options = '' if demo else ' --without-demo=all'
        if lang:
            options += f' --load-language={lang}'
        result = odoo_container.exec_run(
            ['sh', '-c', f'{odoo_command(instance.odoo_version)} -d "$DB" -i base{options} --stop-after-init'],
            environment={'DB': name})
        output = result.output.decode('utf-8', errors='replace')
        print(output[-3000:])
        if result.exit_code != 0 or name not in self._list_user_databases(db_container):
            raise Exception(f'Odoo no pudo crear la base de datos {name}: {output[-800:]}')
        progress(80, 'Contraseña del administrador')
        login = self.set_admin_password(instance, password, databases=[name])
        progress(90, 'Reiniciando Odoo')
        self.restart_instance(instance)
        return login

    def set_admin_password(self, instance, password, databases=None):
        """
        New password for the administrator of every database of the instance (a demo copy).
        Written as the pbkdf2-sha512 hash Odoo checks (12+: res_users.password; 8-11: password_crypt
        when auth_crypt is there, else the plain column). Returns the login of the administrator.
        """
        db_container = self._start_db_container(instance)
        if db_container is None:
            raise Exception('La base de datos de la instancia no existe')
        databases = databases or self._list_user_databases(db_container)
        if not databases:
            raise Exception('La instancia no tiene ninguna base de datos de Odoo')
        major = odoo_major(instance.odoo_version)
        admin_id = 2 if major >= 12 else 1  # base.user_admin (12+) / base.user_root, the admin (8-11)
        # Goes into SQL: only the characters of secrets.token_urlsafe
        if not re.match(r'^[A-Za-z0-9_-]{8,64}$', password):
            raise ValueError('Contraseña con caracteres no admitidos')
        hashed = odoo_password_hash(password)
        login = ''

        def psql(database, sql):
            return self._psql(db_container, database, sql)

        for database in databases:
            if major >= 12:
                psql(database, f"UPDATE res_users SET password = '{hashed}' WHERE id = {admin_id}")
            elif psql(database, "SELECT count(*) FROM information_schema.columns "
                                "WHERE table_name = 'res_users' AND column_name = 'password_crypt'") == '1':
                psql(database, f"UPDATE res_users SET password = NULL, password_crypt = '{hashed}' WHERE id = {admin_id}")
            else:
                psql(database, f"UPDATE res_users SET password = '{password}' WHERE id = {admin_id}")
            if not login or database in (instance.demo_default_db, instance.database_name):
                login = psql(database, f"SELECT login FROM res_users WHERE id = {admin_id}") or login
        return login or 'admin'

    @staticmethod
    def _psql(db_container, database, sql, check=True):
        result = db_container.exec_run(['psql', '-U', 'odoo', '-d', database, '-qAtc', sql],
                                       environment={"PGPASSWORD": "odoo"})
        if check and result.exit_code != 0:
            raise Exception(f"{database}: {result.output.decode(errors='replace')[-300:]}")
        return result.output.decode(errors='replace').strip()

    def neutralize_databases(self, instance, crons=True):
        """
        A copy that must not act as the original: outgoing and incoming mail servers off, API keys dropped,
        payment providers disabled, a new database uuid and, with crons, every scheduled action off but the
        autovacuum (Odoo 16+ also shows its "neutralized" ribbon). Returns notes for the log.
        """
        db_container = self._start_db_container(instance)
        if db_container is None:
            raise Exception('La base de datos de la instancia no existe')
        self._wait_for_postgres(db_container)
        statements = [
            "UPDATE ir_mail_server SET active = false",
            "UPDATE fetchmail_server SET active = false",
            "DELETE FROM res_users_apikeys",
            "UPDATE payment_provider SET state = 'disabled' WHERE state <> 'disabled'",
            "UPDATE payment_acquirer SET state = 'disabled' WHERE state <> 'disabled'",
            "UPDATE ir_config_parameter SET value = md5(random()::text || clock_timestamp()::text)::uuid::text "
            "WHERE key = 'database.uuid'",
        ]
        if crons:
            statements.append("UPDATE ir_cron SET active = false WHERE id NOT IN (SELECT res_id FROM ir_model_data "
                              "WHERE model = 'ir.cron' AND module = 'base' AND name = 'autovacuum_job')")
        if odoo_major(instance.odoo_version) >= 16:
            statements.append("INSERT INTO ir_config_parameter (key, value) VALUES ('database.is_neutralized', 'True') "
                              "ON CONFLICT (key) DO UPDATE SET value = 'True'")
        notes = []
        for database in self._list_user_databases(db_container):
            # Tables that only some versions (or installed modules) have: missing ones are skipped
            for sql in statements:
                self._psql(db_container, database, sql, check=False)
            notes.append(f"{database}: neutralizada (correo{', tareas programadas' if crons else ''}, pagos y claves API desactivados)")
        return notes

    def sanitize_demo(self, instance):
        """
        A demo is a full copy of its template, handed to a visitor as administrator. Before that:
        every other user gets an unknown password (known template passwords stop working), outgoing
        and incoming mail servers are switched off (a demo must not mail real customers), API keys
        are dropped and the database secret and uuid are regenerated. Returns notes for the log.
        """
        import secrets
        db_container = self._start_db_container(instance)
        if db_container is None:
            raise Exception('La base de datos de la instancia no existe')
        major = odoo_major(instance.odoo_version)
        admin_id = 2 if major >= 12 else 1
        unknown = odoo_password_hash(secrets.token_urlsafe(32))
        notes = []
        for database in self._list_user_databases(db_container):
            if major >= 12:
                users = f"UPDATE res_users SET password = '{unknown}' WHERE id <> {admin_id} AND password IS NOT NULL"
            elif self._psql(db_container, database, "SELECT count(*) FROM information_schema.columns "
                            "WHERE table_name = 'res_users' AND column_name = 'password_crypt'") == '1':
                users = f"UPDATE res_users SET password = NULL, password_crypt = '{unknown}' WHERE id <> {admin_id}"
            else:
                users = f"UPDATE res_users SET password = '{secrets.token_urlsafe(32)}' WHERE id <> {admin_id}"
            self._psql(db_container, database, users)
            # Tables that only some versions (or installed modules) have: missing ones are skipped
            for sql in ("UPDATE ir_mail_server SET active = false",
                        "UPDATE fetchmail_server SET active = false",
                        "DELETE FROM res_users_apikeys",
                        "UPDATE ir_config_parameter SET value = md5(random()::text || clock_timestamp()::text) "
                        "WHERE key = 'database.secret'",
                        "UPDATE ir_config_parameter SET value = md5(random()::text || clock_timestamp()::text)::uuid::text "
                        "WHERE key = 'database.uuid'"):
                self._psql(db_container, database, sql, check=False)
            notes.append(f'{database}: otros usuarios sin contraseña conocida, correo desactivado, claves API borradas')
        return notes
