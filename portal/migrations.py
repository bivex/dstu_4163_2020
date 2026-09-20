"""Легкі схематичні міграції для SQLite/PostgreSQL (ідемпотентне додавання колонок)."""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text


def run_migrations(engine: Engine) -> None:
    """Виконати міграції: додати колонки, яких немає у наявній БД."""
    insp = inspect(engine)

    if "users" in insp.get_table_names():
        u_cols = {c["name"] for c in insp.get_columns("users")}
        with engine.begin() as conn:
            if "kep_serial_number" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN kep_serial_number VARCHAR(256)"))
            if "kep_certificate_serial" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN kep_certificate_serial VARCHAR(256)"))
            if "kep_subject_cn" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN kep_subject_cn VARCHAR(256)"))
            # роль для контролю доступу; всім наявним — clerk (мінімум прав)
            if "role" not in u_cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'clerk'")
                )
            # CN сертифіката електронної печатки юрособи (окремо від КЕП особи)
            if "organization_cert_cn" not in u_cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN organization_cert_cn VARCHAR(256)")
                )
            # контакти фізособи-заявника для блоку «від кого» у заявах/скаргах
            if "phone" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(64)"))
            if "address" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN address TEXT"))
            # факсиміле (дигітальне зображення підпису)
            if "facsimile_blob" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN facsimile_blob BLOB"))
            if "facsimile_mime" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN facsimile_mime VARCHAR(32)"))
            if "position" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN position VARCHAR(256) DEFAULT ''"))

    if "signers" in insp.get_table_names():
        s_cols = {c["name"] for c in insp.get_columns("signers")}
        with engine.begin() as conn:
            # тип підписанта: person (КЕП) | seal (електронна печатка юрособи)
            if "signer_type" not in s_cols:
                conn.execute(
                    text(
                        "ALTER TABLE signers ADD COLUMN signer_type VARCHAR(16) DEFAULT 'person'"
                    )
                )
            # дані печатки (eSeal): організація та ідентифікатор
            if "organization" not in s_cols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN organization VARCHAR(256)"))
            if "identifier" not in s_cols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN identifier VARCHAR(128)"))
            if "valid_from" not in s_cols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN valid_from VARCHAR(64)"))
            if "valid_to" not in s_cols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN valid_to VARCHAR(64)"))

    if "documents" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("documents")}
        if "rendered_marked" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE documents ADD COLUMN rendered_marked BLOB"))
        # реєстраційні колонки (авто-нумерація + автодата)
        with engine.begin() as conn:
            if "doc_type" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN doc_type VARCHAR(64)"))
            if "reg_number" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN reg_number INTEGER"))
            if "reg_index" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN reg_index VARCHAR(64)"))
            if "reg_date" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN reg_date VARCHAR(64)"))
            if "registered_at" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN registered_at DATETIME"))
            if "archived_at" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN archived_at DATETIME"))
            if "is_scanned" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN is_scanned BOOLEAN DEFAULT 0"))
            if "folder_id" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN folder_id INTEGER"))
            if "approval_type" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE documents ADD COLUMN approval_type VARCHAR(32) DEFAULT 'sequential'"
                    )
                )
            if "journal_id" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN journal_id INTEGER"))

        # clean up old reg_index values that have the № prefix baked in
        with engine.begin() as conn:
            rows = conn.execute(
                text("SELECT id, reg_index FROM documents WHERE reg_index LIKE :pat"), {"pat": "№%"}
            ).fetchall()
            for row in rows:
                new_val = row[1].lstrip("№ ").lstrip("№")
                if new_val != row[1]:
                    conn.execute(
                        text("UPDATE documents SET reg_index = :v WHERE id = :id"),
                        {"v": new_val, "id": row[0]},
                    )

    # clean up journal templates that have the № prefix baked in
    if "journals" in insp.get_table_names():
        with engine.begin() as conn:
            jrows = conn.execute(
                text("SELECT id, number_template FROM journals WHERE number_template LIKE :pat"),
                {"pat": "№%"},
            ).fetchall()
            for jr in jrows:
                new_tpl = jr[1].lstrip("№ ").lstrip("№").strip()
                if new_tpl != jr[1]:
                    conn.execute(
                        text("UPDATE journals SET number_template = :v WHERE id = :id"),
                        {"v": new_tpl, "id": jr[0]},
                    )

    # approvers: зв'язок погоджувача з користувачем системи (user_id)
    if "approvers" in insp.get_table_names():
        acols = {c["name"] for c in insp.get_columns("approvers")}
        with engine.begin() as conn:
            if "user_id" not in acols:
                conn.execute(text("ALTER TABLE approvers ADD COLUMN user_id INTEGER"))

    # tasks: зв'язок виконавця з користувачем системи (executor_user_id)
    if "tasks" in insp.get_table_names():
        tcols = {c["name"] for c in insp.get_columns("tasks")}
        with engine.begin() as conn:
            if "executor_user_id" not in tcols:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN executor_user_id INTEGER"))
