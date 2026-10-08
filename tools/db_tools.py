import json
import logging
import re
from langchain_core.tools import tool
from core.storage import sql_database

_logger = logging.getLogger(__name__)


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
def get_filenames_paginated(limit: int = 50, offset: int = 0) -> list[str]:
    """
    Retrieve a paginated list of filenames from the database.
    Use this to browse available documents when searching for relevant files.
    """

    _logger.info(
        f"Tool `get_filenames_paginated` called with limit {limit} and offset {offset}..."
    )

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT filename FROM document_metadata LIMIT ? OFFSET ?", (limit, offset)
        )
        rows: list[tuple[str]] = cursor.fetchall()

        _logger.info(f"Retrieved {len(rows)} filenames from DB.")
        if rows:
            return [row[0] for row in rows]
        else:
            return ["No files found in the database."]
    finally:
        conn.close()


@tool
def get_file_details(filename: str) -> str:
    """
    Retrieve detailed metadata and indices for a specific file.
    Use this to inspect a file and determine if its contents might be relevant to the user's query.
    Returns a JSON string containing the metadata and doc_index.
    """

    _logger.info(f"Tool `get_file_details` called for file: {filename}...")

    conn = sql_database.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT metadata, doc_index FROM document_metadata WHERE filename = ?",
            (filename,),
        )
        row: tuple[str, str] | None = cursor.fetchone()
        if row and row[0]:
            _logger.info(f"Details found for {filename}.")
            return json.dumps({"metadata": row[0], "doc_index": row[1]})

        _logger.warning(f"No details found for {filename}.")
        return json.dumps(
            {"error": f"File {filename} not found or no details available."}
        )
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
        cursor.execute("SELECT COUNT(*) FROM document_metadata")
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
            "SELECT DISTINCT codice_regione, denominazione_regione, codice_provincia, denominazione_provincia FROM elenco_comuni_italiani WHERE codice_regione = ?",
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
        query = f"SELECT path FROM spatial WHERE hazard_id = ? AND (region_id = ? OR province_id = ? OR city_id = ?) GROUP BY path"
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
            "SELECT codice_comune_alfanumerico, denominazione_comune FROM elenco_comuni_italiani WHERE codice_provincia = ?",
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
            "SELECT codice_regione, denominazione_regione FROM elenco_comuni_italiani WHERE LOWER(denominazione_regione) = LOWER(?)",
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
            "SELECT codice_provincia, denominazione_provincia, codice_regione, denominazione_regione FROM elenco_comuni_italiani WHERE LOWER(denominazione_provincia) = LOWER(?)",
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
            "SELECT codice_comune_alfanumerico, denominazione_comune, codice_provincia, denominazione_provincia, codice_regione, denominazione_regione FROM elenco_comuni_italiani WHERE LOWER(denominazione_comune) = LOWER(?)",
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
