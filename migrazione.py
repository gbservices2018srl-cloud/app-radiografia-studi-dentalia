"""
Copia una tantum di tutti i dati da un altro database (es. trasloco Oregon -> Francoforte).

Si attiva SOLO se è impostata la variabile d'ambiente MIGRA_DA (URL esterno del vecchio database)
e il database di destinazione è ancora vuoto (nessun utente): così un riavvio dopo il trasloco
non sovrascrive mai i dati nuovi. Finito il trasloco, la variabile MIGRA_DA va tolta da Render.
"""
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text


def _url(u):
    if u.startswith("postgres://"):
        u = "postgresql+psycopg2://" + u[len("postgres://"):]
    elif u.startswith("postgresql://"):
        u = "postgresql+psycopg2://" + u[len("postgresql://"):]
    return u


def copia_dati(url_origine, motore_dest, metadata):
    """Copia le righe di tutte le tabelle di `metadata` dall'origine alla destinazione.
    Restituisce {tabella: righe copiate}, oppure None se la destinazione non era vuota."""
    origine = create_engine(_url(url_origine))
    tabelle = metadata.sorted_tables  # ordine che rispetta le chiavi esterne
    with motore_dest.connect() as c:
        if "utente" in metadata.tables and c.execute(
                select(func.count()).select_from(metadata.tables["utente"])).scalar():
            return None
    ins_o = inspect(origine)
    conteggi = {}
    with origine.connect() as src, motore_dest.begin() as dst:
        # le righe create all'avvio (admin, listino di esempio, dati azienda) vengono sostituite da quelle vere
        for t in reversed(tabelle):
            dst.execute(t.delete())
        for t in tabelle:
            if not ins_o.has_table(t.name):
                conteggi[t.name] = 0
                continue
            col_o = {c["name"] for c in ins_o.get_columns(t.name)}
            colonne = [c for c in t.columns if c.name in col_o]
            t_o = Table(t.name, MetaData(), autoload_with=origine)
            righe = [dict(r._mapping) for r in src.execute(select(*[t_o.c[c.name] for c in colonne]))]
            if righe:
                dst.execute(t.insert(), righe)
            conteggi[t.name] = len(righe)
        if motore_dest.dialect.name == "postgresql":
            for t in tabelle:
                pk = list(t.primary_key.columns)
                if len(pk) == 1 and pk[0].autoincrement in (True, "auto") and str(pk[0].type) == "INTEGER":
                    dst.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('\"{t.name}\"', '{pk[0].name}'), "
                        f"COALESCE((SELECT MAX(\"{pk[0].name}\") FROM \"{t.name}\"), 0) + 1, false)"))
    origine.dispose()
    return conteggi
