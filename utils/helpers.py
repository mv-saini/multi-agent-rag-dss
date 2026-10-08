def json_to_markdown(data):
    if not data:
        return ""

    markdown = ""

    if isinstance(data, dict):
        for key, value in data.items():
            markdown += f"**{key}**:\n"
            if isinstance(value, list):
                for item in value:
                    formatted_item = json_to_markdown(item).strip()
                    markdown += f"- {formatted_item}\n"
            elif isinstance(value, dict):
                markdown += f"{json_to_markdown(value)}\n"
            else:
                markdown += f"{value}\n"

    elif isinstance(data, list):
        for item in data:
            formatted_item = json_to_markdown(item).strip()
            markdown += f"- {formatted_item}\n"

    else:
        markdown += f"{data}\n"

    return markdown


def summarize_locations(geographic_context: list[dict]) -> list[dict]:
    locations = []

    for region in geographic_context or []:
        region_name = region.get("region_name")
        region_id = region.get("region_id")
        provinces = region.get("province") or []

        if not provinces:
            locations.append({"type": "region", "name": region_name, "id": region_id})
            continue

        for province in provinces:
            province_name = province.get("province_name")
            province_id = province.get("province_id")
            cities = province.get("city") or []

            if not cities:
                locations.append(
                    {
                        "type": "province",
                        "name": province_name,
                        "id": province_id,
                        "parent": region_name,
                    }
                )
                continue

            for city in cities:
                locations.append(
                    {
                        "type": "city",
                        "name": city.get("city_name"),
                        "id": city.get("city_id"),
                        "parent": province_name,
                    }
                )

    return locations


def build_display_plan(plan: dict, web_results: list) -> dict:
    selected_tools = plan.get("selected_tools", [])
    vector_tasks = plan.get("vector_tasks", [])
    spatial_context = plan.get("spatial_context", [])

    has_vector = "vector_database" in selected_tools or len(vector_tasks) > 0
    has_spatial = "spatial_database" in selected_tools or len(spatial_context) > 0

    tools = []

    if has_vector:
        tools.append(
            {
                "id": "vector_database",
                "label": "Document database",
                "description": "Searches the document database for relevant information.",
            }
        )

    if has_spatial:
        tools.append(
            {
                "id": "spatial_database",
                "label": "Spatial database",
                "description": "Runs geospatial hazard analysis for the selected locations and hazard layers.",
            }
        )

    document_searches = []
    for idx, task in enumerate(vector_tasks, start=1):
        document_searches.append(
            {
                "title": f"Document {idx}",
                "target_file": task.get("target_file"),
                "queries": task.get("queries", []),
            }
        )

    spatial_analyses = []
    for idx, ctx in enumerate(spatial_context, start=1):
        hazards = [
            {"id": hazard.get("hazard_id"), "name": hazard.get("hazard_name")}
            for hazard in ctx.get("hazard", [])
        ]

        locations = summarize_locations(ctx.get("geographic_context", []))

        spatial_analyses.append(
            {
                "title": f"Spatial analysis {idx}",
                "hazards": hazards,
                "locations": locations,
            }
        )

    return {
        "title": "Plan",
        "tools": tools,
        "document_searches": document_searches,
        "spatial_analyses": spatial_analyses,
        "web_results": web_results,
    }


def format_spatial_analysis(
    spatial_analysis: list[dict],
) -> str:
    if not spatial_analysis:
        return ""

    lines = []

    location_fields = {
        "type": "Type",
        "total_area_sqkm": "Total area km2",
        "total_population": "Total population",
        "total_residential_houses": "Total residential houses",
        "total_residential_buildings": "Total residential buildings",
        "total_families": "Total families",
    }

    common_stat_fields = {
        "geometry_type": "Geometry",
        "total_points": "Hazard points in territory",
        "estimated_grid_resolution_meters": "Estimated grid resolution meters",
        "max_intensity_recorded": "Maximum intensity recorded",
    }

    breakdown_sections = {
        "intensity_breakdown": "Risk tier breakdown",
        "seismic_discrete_zones": "Seismic risk zone breakdown",
        "multi_hazard_spatial_breakdown": "Multi-hazard risk breakdown",
    }

    breakdown_metric_labels = {
        "affected_area_sqkm": "Affected area km2",
        "exposed_area_proxy_sqkm": "Exposed area proxy km2",
        "percent_of_territory": "Territory affected %",
        "point_count": "Hazard point count",
        "exposed_population": "Population exposed",
        "exposed_residential_houses": "Residential houses exposed",
        "exposed_residential_buildings": "Residential buildings exposed",
        "exposed_families": "Families exposed",
        "housing_occupancy_percentage": "Housing occupancy %",
        "average_people_per_building": "Average people per building",
    }

    overlap_fields = {
        "total_overlap_area_sqkm": "Total overlap area km2",
        "percent_of_territory": "Territory affected %",
        "total_exposed_population": "Total exposed population",
        "total_exposed_buildings": "Total exposed buildings",
    }

    overlap_breakdown_labels = {
        "overlap_area_sqkm": "Overlap area km2",
        "exposed_population": "Population exposed",
    }

    for idx, analysis in enumerate(
        spatial_analysis,
        start=1,
    ):
        if not analysis:
            continue

        location = analysis.get("location") or {}
        hazards = analysis.get("hazard_metrics") or []
        overlaps = (
            analysis.get("hazard_overlaps") or []
        )  # --- NEW: Extract overlaps ---

        location_name = location.get("name", "Unknown")

        lines.append(f"### SPATIAL ANALYSIS {idx}")
        lines.append(f"##LOCATION: {location_name}")

        for key, label in location_fields.items():
            value = location.get(key)

            if value is not None:
                lines.append(f"- {label}: {value}")

        lines.append("")

        if not hazards:
            lines.append("- No hazard analysis results were returned.")
            lines.append("")
            continue

        for hazard in hazards:
            if not hazard:
                continue

            hazard_name = hazard.get(
                "hazard_type",
                "Unknown hazard",
            )

            lines.append(f"### Hazard: {hazard_name}")

            hazard_error = hazard.get("error")
            if hazard_error:
                lines.append(f"- Error: {hazard_error}")
                lines.append("")
                continue

            stats = hazard.get("statistics")

            if stats is None:
                lines.append(
                    "- Status: No hazard features were found "
                    "inside the selected location."
                )
                lines.append("")
                continue

            if not isinstance(stats, dict):
                lines.append(
                    "- Status: Spatial statistics were returned "
                    "in an unsupported format."
                )
                lines.append("")
                continue

            stats_error = stats.get("error")
            if stats_error:
                lines.append(f"- Error: {stats_error}")
                lines.append("")
                continue

            stats_status = stats.get("status")
            if stats_status:
                lines.append(f"- Status: {stats_status}")
                lines.append("")
                continue

            for key, label in common_stat_fields.items():
                value = stats.get(key)

                if value is not None:
                    lines.append(f"- {label}: {value}")

            seismic_acceleration = stats.get("seismic_acceleration_ag")

            if isinstance(seismic_acceleration, dict):
                lines.append("- Seismic acceleration ag:")

                for metric in ("min", "mean", "max"):
                    value = seismic_acceleration.get(metric)

                    if value is not None:
                        lines.append(f"  - {metric.capitalize()}: {value}")

            found_breakdown = False

            for (
                section_key,
                section_title,
            ) in breakdown_sections.items():
                breakdown = stats.get(section_key)

                if not isinstance(breakdown, dict):
                    continue

                found_breakdown = True
                lines.append("")
                lines.append(f"{section_title}:")

                for tier_name, tier_stats in breakdown.items():
                    lines.append(f"- {tier_name}:")

                    if not tier_stats:
                        lines.append(
                            "  - No features or exposure were " "recorded in this tier."
                        )
                        continue

                    if not isinstance(tier_stats, dict):
                        lines.append(f"  - Value: {tier_stats}")
                        continue

                    metric_found = False

                    for metric_key, metric_label in breakdown_metric_labels.items():
                        if metric_key not in tier_stats:
                            continue

                        metric_value = tier_stats.get(metric_key)

                        if metric_value is None:
                            continue

                        lines.append(f"  - {metric_label}: " f"{metric_value}")
                        metric_found = True

                    for (
                        metric_key,
                        metric_value,
                    ) in tier_stats.items():
                        if (
                            metric_key in breakdown_metric_labels
                            or metric_value is None
                        ):
                            continue

                        label = metric_key.replace(
                            "_",
                            " ",
                        ).capitalize()

                        lines.append(f"  - {label}: {metric_value}")
                        metric_found = True

                    if not metric_found:
                        lines.append("  - No metrics available.")

            if not found_breakdown:
                lines.append("- No risk-tier breakdown was available.")

            lines.append("")

        if overlaps:
            lines.append("### Hazard Overlaps (Co-occurring Risks)")
            for overlap in overlaps:
                combo_name = overlap.get("combination", "Unknown combination")
                lines.append(f"#### Combination: {combo_name}")

                for key, label in overlap_fields.items():
                    value = overlap.get(key)
                    if value is not None:
                        lines.append(f"- {label}: {value}")

                severity_breakdowns = overlap.get("severity_breakdown")
                if severity_breakdowns and isinstance(severity_breakdowns, list):
                    lines.append("  - Severity Breakdown:")
                    for severity in severity_breakdowns:
                        risk_parts = []
                        stat_parts = []

                        for k, v in severity.items():
                            if k.endswith("_risk"):
                                risk_name = (
                                    k.replace("_risk", "").replace("_", " ").title()
                                )
                                risk_parts.append(f"{risk_name}: {v}")
                            else:
                                label = overlap_breakdown_labels.get(
                                    k, k.replace("_", " ").capitalize()
                                )
                                stat_parts.append(f"{label}: {v}")

                        combo_str = " + ".join(risk_parts)
                        stats_str = ", ".join(stat_parts)
                        lines.append(f"    - [{combo_str}] => {stats_str}")
                lines.append("")

    return "\n".join(lines).strip()


def format_vector_docs(vector_docs: list) -> str:
    if not vector_docs:
        return ""

    lines = []

    for i, chunk in enumerate(vector_docs, start=1):
        if isinstance(chunk, dict):
            metadata = chunk.get("metadata", {})
            content = chunk.get("page_content", "")
        else:
            metadata = getattr(chunk, "metadata", {})
            content = getattr(chunk, "page_content", "")

        source = (
            metadata.get("source", "Unknown")
            if isinstance(metadata, dict)
            else "Unknown"
        )
        page = (
            metadata.get("page", "Unknown") if isinstance(metadata, dict) else "Unknown"
        )

        lines.append(f"## Document Evidence [{i}]")
        lines.append(f"- Source: {source}")
        lines.append(f"- Page: {page}")
        lines.append("- Content:")
        lines.append(content.strip())
        lines.append("")

    return "\n".join(lines)


def format_web_results(web_results: list, offset=0) -> str:
    if not web_results:
        return ""

    lines = []

    for i, result in enumerate(web_results, start=1 + offset):
        url = result.get("url", "Unknown")
        title = result.get("title", "Unknown")
        content = result.get("content", "No content available.")

        lines.append(f"## Web Result [{i}]")
        lines.append(f"- Title: {title}")
        lines.append(f"- URL: {url}")
        lines.append("- Content:")
        lines.append(content.strip())
        lines.append("")

    return "\n".join(lines)
