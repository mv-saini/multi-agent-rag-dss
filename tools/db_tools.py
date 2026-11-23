import json
import logging
import re
from langchain_core.tools import tool
from core.storage import sql_database

_logger = logging.getLogger(__name__)
_DISCOVERY_SUMMARY_PREVIEW_CHARS = 900
_DEFAULT_SECTION_LIMIT = 12


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _compact_catalog_record(document_id, filename: str, metadata) -> dict:
    metadata = _as_dict(metadata)
    discovery_summary = _as_dict(metadata.get("discovery_summary"))
    keywords = discovery_summary.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    return {
        "document_id": str(document_id),
        "filename": filename,
        "title": metadata.get("doc_title", ""),
        "summary": str(discovery_summary.get("text", ""))[
            :_DISCOVERY_SUMMARY_PREVIEW_CHARS
        ],
        "summary_source": discovery_summary.get("source", ""),
        "keywords": [str(keyword) for keyword in keywords[:12]],
    }


def _section_entries(doc_index, limit: int, offset: int) -> tuple[list[dict], int]:
    index = _as_dict(doc_index)
    entries = list(index.values())
    return entries[offset : offset + limit], len(entries)


def _is_select_query(query: str) -> bool:
    stripped_query = query.strip()
    while True:
        if stripped_query.startswith("--"):
            newline_index = stripped_query.find("\n")
            if newline_index == -1:
                return False
            stripped_query = stripped_query[newline_index + 1 :].lstrip()
            continue

        if stripped_query.startswith("/*"):
            comment_end = stripped_query.find("*/")
            if comment_end == -1:
                return False
            stripped_query = stripped_query[comment_end + 2 :].lstrip()
            continue

        break

    return bool(re.match(r"^select\b", stripped_query, re.IGNORECASE))


@tool
def get_documents_paginated(limit: int = 50, offset: int = 0) -> list[dict]:
    """
    Retrieve document UUIDs and display filenames from the database.
    Use this to browse available documents beyond catalog search results.
    """

    _logger.info(
        "Tool `get_documents_paginated` called with limit %s and offset %s...",
        limit,
        offset,
    )

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT document_id, filename FROM documents "
            "ORDER BY LOWER(filename), document_id LIMIT %s OFFSET %s",
            (limit, offset),
        )
        rows = cursor.fetchall()

        _logger.info("Retrieved %d documents from DB.", len(rows))
        return [
            {"document_id": str(document_id), "filename": filename}
            for document_id, filename in rows
        ]
    finally:
        conn.close()


@tool
def search_document_catalog(query: str = "", limit: int = 10) -> list[dict]:
    """Search compact document-selection metadata without loading section indexes.

    Use this first when discovering sources. Results contain a filename, title,
    discovery-summary preview, and keywords. Query can be empty to browse.
    """
    limit = max(1, min(limit, 25))
    terms = [term for term in re.findall(r"[^\W_]+", query) if len(term) > 1]
    conditions = []
    parameters = []
    for term in terms[:6]:
        conditions.append("(filename ILIKE %s OR metadata::text ILIKE %s)")
        pattern = f"%{term}%"
        parameters.extend([pattern, pattern])

    statement = "SELECT document_id, filename, metadata FROM documents"
    if conditions:
        statement += " WHERE " + " AND ".join(conditions)
    statement += " ORDER BY LOWER(filename), document_id LIMIT %s"
    parameters.append(limit)

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(statement, parameters)
        return [
            _compact_catalog_record(document_id, filename, metadata)
            for document_id, filename, metadata in cursor.fetchall()
        ]
    finally:
        conn.close()


@tool
def get_file_details(
    document_id: str,
    summary_chars: int = 1_500,
    section_limit: int = _DEFAULT_SECTION_LIMIT,
) -> dict:
    """
    Retrieve compact discovery metadata and a bounded section-index preview.
    Use only for a small number of plausible candidates after catalog search.
    """

    _logger.info("Tool `get_file_details` called for document: %s...", document_id)

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT filename, metadata, doc_index "
            "FROM documents WHERE document_id = %s",
            (document_id,),
        )
        row = cursor.fetchone()
        if row and row[1]:
            filename = row[0]
            _logger.info("Details found for document %s.", document_id)
            metadata = _as_dict(row[1])
            discovery_summary = _as_dict(metadata.get("discovery_summary"))
            summary_chars = max(200, min(summary_chars, 3_000))
            section_limit = max(1, min(section_limit, 30))
            sections, total_sections = _section_entries(row[2], section_limit, 0)
            return {
                "document_id": document_id,
                "filename": filename,
                "title": metadata.get("doc_title", ""),
                "discovery_summary": {
                    "source": discovery_summary.get("source", ""),
                    "text": str(discovery_summary.get("text", ""))[
                        :summary_chars
                    ],
                    "keywords": discovery_summary.get("keywords", [])[:12],
                },
                "sections": sections,
                "total_sections": total_sections,
            }

        _logger.warning("No details found for document %s.", document_id)
        return {"error": f"Document {document_id} not found or has no metadata."}
    finally:
        conn.close()


@tool
def get_document_sections(
    document_id: str, limit: int = 20, offset: int = 0
) -> dict:
    """Get a bounded page of section headings for one already-selected candidate."""
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT filename, doc_index FROM documents WHERE document_id = %s",
            (document_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {"error": f"Document {document_id} not found."}
        sections, total_sections = _section_entries(row[1], limit, offset)
        return {
            "document_id": document_id,
            "filename": row[0],
            "sections": sections,
            "offset": offset,
            "total_sections": total_sections,
        }
    finally:
        conn.close()


def get_files_count() -> int:
    """
    Retrieve the total count of files in the database.
    """

    _logger.info(f"Tool `get_files_count` called to retrieve total file count...")

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM documents")
        row: tuple[int] | None = cursor.fetchone()
        if row:
            _logger.info(f"Total files in DB: {row[0]}.")
            return row[0]

        _logger.warning("No files found in the database.")
        return 0
    finally:
        conn.close()


@tool
def get_regions() -> list[str]:
    """
    Retrieve a list of unique regions from the database.
    Use this to get geographical context when dealing with spatial data queries.
    """
    _logger.info(f"Tool `get_regions` called to retrieve unique regions...")
    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT DISTINCT codice_regione, denominazione_regione FROM elenco_comuni_italiani"
        )
        rows: list[tuple[str, str]] = cursor.fetchall()

        if rows:
            _logger.info(f"Retrieved {len(rows)} unique regions.")
            return [{"region_id": row[0], "region": row[1]} for row in rows]

        _logger.warning("No regions found in the database.")
        return ["there are no regions available in the database."]
    finally:
        conn.close()


@tool
def get_provinces(region_id: str) -> list[dict]:
    """
    Retrieve a list of provinces for a given region.
    Use this to get geographical context when dealing with spatial data queries.
    """
    _logger.info(f"Tool `get_provinces` called for region: {region_id}...")
    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT DISTINCT codice_regione, denominazione_regione, codice_provincia, denominazione_provincia FROM elenco_comuni_italiani WHERE codice_regione = %s",
            (region_id,),
        )
        rows: list[tuple[str, str, str, str]] = cursor.fetchall()

        if rows:
            _logger.info(f"Retrieved {len(rows)} provinces for region {region_id}.")
            return [
                {
                    "region_id": row[0],
                    "region": row[1],
                    "province_id": row[2],
                    "province": row[3],
                }
                for row in rows
            ]

        _logger.warning(f"No provinces found for region {region_id}.")
        return [
            "there are no provinces available in the database for the given region_id."
        ]
    finally:
        conn.close()


@tool
def get_hazard_data_file_paths(
    hazard_id: int, region_id: int, province_id: int, city_id: int
) -> list[str]:
    """
    Retrieve a list of hazard data file paths associated with a specific hazards.
    Use this to find relevant spatial data file paths.
    If the result if empty then their are no hazard data files associated with the given hazard_id and geographical context.
    """
    _logger.info(
        f"Tool `get_hazard_data_file_paths` called for hazard_id: {hazard_id}..."
    )
    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        query = "SELECT path FROM spatial WHERE hazard_id = %s AND (region_id = %s OR province_id = %s OR city_id = %s) GROUP BY path"
        cursor.execute(query, (hazard_id, region_id, province_id, city_id))
        rows: list[tuple[str]] = cursor.fetchall()

        if rows:
            _logger.info(
                f"Retrieved {len(rows)} hazard data files for hazard id {hazard_id}."
            )
            return [row[0] for row in rows]

        _logger.warning(f"No hazard data files found for hazard id {hazard_id}.")
        return [
            "there are no hazard data files associated with the given hazard_id and geographical context."
        ]
    finally:
        conn.close()


@tool
def get_hazard_ids() -> list[dict]:
    """
    Retrieve a list of unique hazard types from the database.
    Use this to understand what types of hazard data are available when dealing with spatial data queries.
    """
    _logger.info(f"Tool `get_hazard_ids` called to retrieve unique hazard types...")
    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT hazard_id, hazard FROM hazard_types")
        rows: list[tuple[str, str]] = cursor.fetchall()

        if rows:
            _logger.info(f"Retrieved {len(rows)} unique hazard types.")
            return [{"hazard_id": row[0], "hazard": row[1]} for row in rows]

        _logger.warning("No hazard types found in the database.")
        return ["there are no hazard types available in the database."]
    finally:
        conn.close()


@tool
def get_cities(province_id: int):
    """
    Retrieve a list of cities for a given province.
    Use this to get geographical context when dealing with spatial data queries.
    """
    _logger.info(f"Tool `get_cities` called for province_id: {province_id}...")

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT codice_comune_alfanumerico, denominazione_comune FROM elenco_comuni_italiani WHERE codice_provincia = %s",
            (province_id,),
        )
        rows: list[tuple[str, str]] = cursor.fetchall()

        if rows:
            _logger.info(f"Retrieved {len(rows)} cities for province id {province_id}.")
            return [{"city_id": row[0], "city": row[1]} for row in rows]

        _logger.warning(f"No cities found for province id {province_id}.")
        return [
            "there are no cities available in the database for the given province_id."
        ]
    finally:
        conn.close()


def get_region_by_name(region_name: str) -> dict:
    """
    Retrieve region details by region name.
    Use this to get geographical context when dealing with spatial data queries.
    """
    _logger.info(f"Tool `get_region_by_name` called for region_name: {region_name}...")

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT codice_regione, denominazione_regione FROM elenco_comuni_italiani WHERE LOWER(denominazione_regione) = LOWER(%s)",
            (region_name,),
        )
        row: tuple[str, str] | None = cursor.fetchone()

        if row:
            _logger.info(f"Region found for name {region_name}.")
            return {"region_id": row[0], "region": row[1]}
        _logger.warning(f"No region found for name {region_name}.")
        return {"error": f"No region found for name {region_name}."}
    finally:
        conn.close()


def get_province_by_name(province_name: str) -> dict:
    """
    Retrieve province details by province name.
    Use this to get geographical context when dealing with spatial data queries.
    """
    _logger.info(
        f"Tool `get_province_by_name` called for province_name: {province_name}..."
    )

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT codice_provincia, denominazione_provincia, codice_regione, denominazione_regione FROM elenco_comuni_italiani WHERE LOWER(denominazione_provincia) = LOWER(%s)",
            (province_name,),
        )
        row: tuple[str, str, str, str] | None = cursor.fetchone()

        if row:
            _logger.info(f"Province found for name {province_name}.")
            return {
                "province_id": row[0],
                "province": row[1],
                "region_id": row[2],
                "region": row[3],
            }
        _logger.warning(f"No province found for name {province_name}.")
        return {"error": f"No province found for name {province_name}."}
    finally:
        conn.close()


@tool
def get_city_by_name(city_name: str) -> dict:
    """
    Retrieve city details by city name.
    Use this to get geographical context when dealing with spatial data queries.
    """
    _logger.info(f"Tool `get_city_by_name` called for city_name: {city_name}...")

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT codice_comune_alfanumerico, denominazione_comune, codice_provincia, denominazione_provincia, codice_regione, denominazione_regione FROM elenco_comuni_italiani WHERE LOWER(denominazione_comune) = LOWER(%s)",
            (city_name,),
        )
        row: tuple[str, str, str, str, str, str] | None = cursor.fetchone()

        if row:
            _logger.info(f"City found for name {city_name}.")
            return {
                "city_id": row[0],
                "city": row[1],
                "province_id": row[2],
                "province": row[3],
                "region_id": row[4],
                "region": row[5],
            }
        _logger.warning(f"No city found for name {city_name}.")
        return {"error": f"No city found for name {city_name}."}
    finally:
        conn.close()


@tool
def execute_sql_query(query: str) -> list[dict]:
    """
    Execute a custom SQL query against the database and return the results.
    Use this for advanced querying needs that are not covered by the other tools, but be cautious of SQL injection risks.
    """
    _logger.info(f"Tool `execute_sql_query` called with query: {query}...")
    if not _is_select_query(query):
        message = "Only SELECT queries are allowed."
        _logger.warning(message)
        return [{"error": message}]

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query)
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()

        _logger.info(f"Executed custom SQL query. Retrieved {len(rows)} rows.")
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        _logger.error(f"Error executing SQL query: {e}")
        return [{"error": str(e)}]
    finally:
        conn.close()
