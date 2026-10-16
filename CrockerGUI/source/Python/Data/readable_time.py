"""Add readable machine-local dates without altering acquisition timestamps."""


def add_readable_times(connection, tables):
    for table, fields in tables.items():
        columns = [r[1] for r in connection.execute(f'PRAGMA table_info("{table}")')]
        for field in fields:
            name = field + '_local'
            if name not in columns:
                connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" TEXT')
            # SQLite localtime uses the recording computer's configured timezone.
            date = f"strftime('%m/%d/%Y', {field}, 'unixepoch', 'localtime')"
            hour = f"CAST(strftime('%H', {field}, 'unixepoch', 'localtime') AS INTEGER)"
            clock = f"strftime(':%M:%S', {field}, 'unixepoch', 'localtime')"
            value = (f"CASE WHEN {field} IS NULL THEN NULL ELSE {date} || ' ' || "
                     f"(({hour} + 11) % 12 + 1) || {clock} || "
                     f"CASE WHEN {hour} < 12 THEN ' AM' ELSE ' PM' END END")
            connection.execute(f'UPDATE "{table}" SET "{name}"={value} WHERE "{name}" IS NULL AND "{field}" IS NOT NULL')
            for action, suffix in [('INSERT', 'insert'), (f'UPDATE OF "{field}"', 'update')]:
                connection.execute(f'''CREATE TRIGGER IF NOT EXISTS "{table}_{field}_local_{suffix}"
                    AFTER {action} ON "{table}" BEGIN
                    UPDATE "{table}" SET "{name}"={value} WHERE rowid=NEW.rowid;
                    END''')
        # ALTER TABLE appends columns. Offer adjacent dates without rebuilding
        # existing tables, primary keys, indexes or foreign-key relationships.
        columns = [r[1] for r in connection.execute(f'PRAGMA table_info("{table}")')]
        dates = {f + '_local' for f in fields}
        ordered = []
        for column in columns:
            if column in dates:
                continue
            ordered.append('"' + column + '"')
            if column in fields:
                ordered.append('"' + column + '_local"')
        connection.execute(f'CREATE VIEW IF NOT EXISTS "{table}_readable" AS SELECT {",".join(ordered)} FROM "{table}"')
