<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import maplibregl, {
  LngLatBounds,
  Map as MapLibreMap,
  Popup
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Geometry } from "geojson";
import type { HazardMapLayer } from "@/types/app";

const props = defineProps<{
  layers: HazardMapLayer[];
  allLayers?: HazardMapLayer[];
  overlay?: boolean;
  hideControls?: boolean;
}>();

const mapContainer = ref<HTMLDivElement | null>(null);
const map = shallowRef<MapLibreMap | null>(null);
const popup = shallowRef<Popup | null>(null);

const activeLayerId = ref<string>("");

interface ManagedLayer {
  layer: HazardMapLayer;
  sourceId: string;
  signature: string;
  ids: string[];
  visible: boolean;
  click: (event: maplibregl.MapLayerMouseEvent) => void;
}

interface ManagedSource {
  data: HazardMapLayer["geojson"] | HazardMapLayer["raster_image"];
}

const managedLayers = new Map<string, ManagedLayer>();
const managedSources = new Map<string, ManagedSource>();
const boundsCache = new WeakMap<object, LngLatBounds>();
let mapReady = false;
let hasFittedBounds = false;
let layerOrder = "";

const activeLayer = computed(() => {
  return (
    props.layers.find(layer => layer.layer_id === activeLayerId.value) ||
    props.layers[0] ||
    null
  );
});

onMounted(async () => {
  await nextTick();
  initMap();
});

onBeforeUnmount(() => {
  clearManagedLayers();

  if (popup.value) {
    popup.value.remove();
    popup.value = null;
  }

  if (map.value) {
    map.value.remove();
    map.value = null;
  }
});

watch(
  [() => props.layers, () => props.allLayers, () => props.hideControls, activeLayerId],
  () => updateMapLayer(),
  { flush: "post" }
);

const initMap = () => {
  if (!mapContainer.value || map.value) return;

  const currentMap = new maplibregl.Map({
    container: mapContainer.value,
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: [
            "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
            "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
            "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png"
          ],
          tileSize: 256,
          attribution: "© OpenStreetMap contributors"
        }
      },
      layers: [
        {
          id: "osm",
          type: "raster",
          source: "osm"
        }
      ]
    },
    center: [12.5, 41.9],
    zoom: 5
  });

  map.value = currentMap;

  currentMap.addControl(new maplibregl.NavigationControl(), "top-right");

  currentMap.on("load", () => {
    mapReady = true;
    updateMapLayer();
  });
};

const sourceIdFor = (layer: HazardMapLayer) =>
  `hazard-source-${encodeURIComponent(layer.raster_image ? layer.layer_id : layer.geojson_source || layer.layer_id)}-${layer.raster_image ? "image" : "geojson"}`;

const updateMapLayer = () => {
  const currentMap = map.value;
  if (!currentMap || !mapReady) return;

  // Retain disabled layers, but release layers removed from the available data.
  const available = props.allLayers ?? props.layers;
  const availableById = new Map(available.map(layer => [layer.layer_id, layer]));
  const orderedLayers = [...props.layers].sort((a, b) =>
    (a.hazard_name === 'Scenario fault' ? 2 : Number(a.geometry_type === 'Point')) -
    (b.hazard_name === 'Scenario fault' ? 2 : Number(b.geometry_type === 'Point')));
  const visibleIds = new Set<string>();

  for (const layer of orderedLayers) {
    if ((!layer.geojson && !layer.raster_image) || layer.empty) continue;
    if (layer.scenario_group && layer.hazard_name !== 'Scenario fault' && !props.hideControls) {
      const selected = activeLayer.value?.scenario_group === layer.scenario_group
        ? activeLayer.value.layer_id : layer.scenario_group;
      if (layer.layer_id !== selected) continue;
    }
    visibleIds.add(layer.layer_id);
    const sourceId = sourceIdFor(layer);
    const data = layer.raster_image ?? availableById.get(layer.geojson_source || layer.layer_id)?.geojson ?? layer.geojson;
    const source = managedSources.get(sourceId);
    if (!source) {
      if (layer.raster_image) {
        currentMap.addSource(sourceId, { type: "image", ...layer.raster_image });
      } else {
        currentMap.addSource(sourceId, { type: "geojson", data: data as HazardMapLayer["geojson"] });
      }
      managedSources.set(sourceId, { data });
    } else if (source.data !== data) {
      if (layer.raster_image) {
        (currentMap.getSource(sourceId) as maplibregl.ImageSource).updateImage(layer.raster_image);
      } else {
        (currentMap.getSource(sourceId) as maplibregl.GeoJSONSource).setData(data as HazardMapLayer["geojson"]);
      }
      source.data = data;
    }

    const signature = JSON.stringify([sourceId, layer.style_property, layer.render_style, layer.hazard_name]);
    let entry = managedLayers.get(layer.layer_id);
    if (entry && entry.signature !== signature) {
      removeManagedLayer(layer.layer_id);
      entry = undefined;
    }
    if (!entry) {
      addHazardLayer(layer, sourceId, signature);
    } else {
      entry.layer = layer;
      if (!entry.visible) {
        for (const id of entry.ids) currentMap.setLayoutProperty(id, "visibility", "visible");
        entry.visible = true;
      }
    }
  }

  for (const [id, entry] of managedLayers) {
    if (!availableById.has(id)) {
      removeManagedLayer(id);
    } else if (!visibleIds.has(id) && entry.visible) {
      for (const mapLayerId of entry.ids) currentMap.setLayoutProperty(mapLayerId, "visibility", "none");
      entry.visible = false;
    }
  }
  const usedSources = new Set([...managedLayers.values()].map(entry => entry.sourceId));
  for (const id of managedSources.keys()) {
    if (!usedSources.has(id)) {
      currentMap.removeSource(id);
      managedSources.delete(id);
    }
  }

  const orderedIds = orderedLayers.flatMap(layer =>
    visibleIds.has(layer.layer_id) ? managedLayers.get(layer.layer_id)?.ids ?? [] : []);
  const nextOrder = JSON.stringify(orderedIds);
  if (layerOrder !== nextOrder) {
    for (const id of orderedIds) currentMap.moveLayer(id);
    layerOrder = nextOrder;
  }
  if (!hasFittedBounds) fitToAllLayers();
};

const fitToAllLayers = () => {
  if (!map.value || !mapReady) return;
  const bounds = new LngLatBounds();
  const seen = new Set<object>();
  const availableById = new Map((props.allLayers ?? props.layers).map(layer => [layer.layer_id, layer]));
  for (const layer of props.layers) {
    if (layer.empty) continue;
    const data = layer.raster_image ?? availableById.get(layer.geojson_source || layer.layer_id)?.geojson ?? layer.geojson;
    if (!data || seen.has(data)) continue;
    seen.add(data);
    let cached = boundsCache.get(data);
    if (!cached) {
      cached = new LngLatBounds();
      if ("coordinates" in data) {
        for (const coordinate of data.coordinates) cached.extend(coordinate);
      } else {
        for (const feature of data.features) extendBoundsWithGeometry(cached, feature.geometry);
      }
      boundsCache.set(data, cached);
    }
    if (!cached.isEmpty()) {
      bounds.extend(cached.getSouthWest());
      bounds.extend(cached.getNorthEast());
    }
  }
  if (!bounds.isEmpty()) {
    map.value.fitBounds(bounds, { padding: 40, maxZoom: 13, duration: 0 });
    hasFittedBounds = true;
  }
};

const addHazardLayer = (hazardLayer: HazardMapLayer, sourceId: string, signature: string) => {
  if (!map.value) return;

  const currentMap = map.value;

  const suffix = encodeURIComponent(hazardLayer.layer_id);
  const fillLayerId = `hazard-fill-${suffix}`;
  const outlineLayerId = `hazard-outline-${suffix}`;
  const pointLayerId = `hazard-point-${suffix}`;
  const entry: ManagedLayer = {
    layer: hazardLayer, sourceId, signature, ids: [], visible: true,
    click: event => handleFeatureClick(event, entry.layer)
  };
  managedLayers.set(hazardLayer.layer_id, entry);

  if (hazardLayer.raster_image) {
    currentMap.addLayer({
      id: fillLayerId, type: "raster", source: sourceId,
      paint: { "raster-opacity": 1, "raster-resampling": "nearest", "raster-fade-duration": 0 }
    });
    entry.ids.push(fillLayerId);
    return;
  }

  currentMap.addLayer({
    id: fillLayerId,
    type: "fill",
    source: sourceId,
    filter: [
      "any",
      ["==", ["geometry-type"], "Polygon"],
      ["==", ["geometry-type"], "MultiPolygon"]
    ],
    paint: {
      "fill-color": ["coalesce", ["get", hazardLayer.style_property || "risk_color"], "#9e9e9e"],
      "fill-opacity": hazardLayer.render_style?.opacity ?? 0.45
    }
  });

  currentMap.addLayer({
    id: outlineLayerId,
    type: "line",
    source: sourceId,
    filter: [
      "any",
      ["==", ["geometry-type"], "Polygon"],
      ["==", ["geometry-type"], "MultiPolygon"]
    ],
    paint: {
      "line-color": hazardLayer.render_style?.outline_color ?? "#000000",
      "line-width": hazardLayer.render_style?.outline_width ?? 1
    }
  });

  currentMap.addLayer({
    id: pointLayerId,
    type: "circle",
    source: sourceId,
    filter: [
      "any",
      ["==", ["geometry-type"], "Point"],
      ["==", ["geometry-type"], "MultiPoint"]
    ],
    paint: {
      "circle-radius": hazardLayer.render_style?.point_radius ?? (hazardLayer.hazard_name?.toLowerCase() === 'seismic' ? 5 : 3),
      "circle-color": ["coalesce", ["get", hazardLayer.style_property || "risk_color"], "#9e9e9e"],
      "circle-opacity": hazardLayer.render_style?.opacity ?? 0.45,
      "circle-stroke-color": "#000000",
      "circle-stroke-width": hazardLayer.render_style?.outline_width ?? 1
    }
  });

  for (const mapLayerId of [fillLayerId, outlineLayerId, pointLayerId]) {
    entry.ids.push(mapLayerId);
    currentMap.on("click", mapLayerId, entry.click);

    currentMap.on("mouseenter", mapLayerId, handleMouseEnter);
    currentMap.on("mouseleave", mapLayerId, handleMouseLeave);
  }
};

const removeManagedLayer = (id: string) => {
  const currentMap = map.value;
  const entry = managedLayers.get(id);
  if (!currentMap || !entry) return;
  for (const layerId of [...entry.ids].reverse()) {
    if (!entry.layer.raster_image) {
      currentMap.off("click", layerId, entry.click);
      currentMap.off("mouseenter", layerId, handleMouseEnter);
      currentMap.off("mouseleave", layerId, handleMouseLeave);
    }
    if (currentMap.getLayer(layerId)) currentMap.removeLayer(layerId);
  }
  managedLayers.delete(id);
  layerOrder = "";
};

const clearManagedLayers = () => {
  if (!map.value) return;
  for (const id of managedLayers.keys()) removeManagedLayer(id);
  for (const id of managedSources.keys()) {
    if (map.value.getSource(id)) map.value.removeSource(id);
  }
  managedSources.clear();
  mapReady = false;
};

const handleFeatureClick = (
  event: maplibregl.MapLayerMouseEvent,
  hazardLayer: HazardMapLayer
) => {
  const currentMap = map.value;
  if (!currentMap || !event.features?.length) return;

  const feature = event.features[0];
  if (!feature) return;
  const properties = feature.properties || {};

  const riskLabel = properties[hazardLayer.label_property || "risk_label"] || "Unclassified";

  if (popup.value) {
    popup.value.remove();
  }

  popup.value = new maplibregl.Popup()
    .setLngLat(event.lngLat)
    .setHTML(`
      <div style="min-width: 240px">
        <strong>${escapeHtml(hazardLayer.layer_name)}</strong><br />
        <div style="margin-top: 4px;">
          ${hazardLayer.view_label ? escapeHtml(hazardLayer.view_label) : hazardLayer.hazard_name === 'Seismic scenario' ? 'Median shaking' : 'Risk'}: <strong>${escapeHtml(String(riskLabel))}</strong>
        </div>

        ${renderPopupMetric(
      "Affected area",
      properties.affected_area_sqkm,
      " km²"
    )}

        ${renderPopupMetric(
      "Territory affected",
      properties.percent_of_territory,
      "%"
    )}

        ${renderPopupMetric(
      "Population exposed",
      properties.exposed_population
    )}

        ${renderPopupMetric(
      "Buildings exposed",
      properties.exposed_residential_buildings
    )}

        ${renderPopupMetric(
      "Houses exposed",
      properties.exposed_residential_houses
    )}

        ${renderPopupMetric(
      "Families exposed",
      properties.exposed_families
    )}

        ${renderPopupMetric(
      "Seismic acceleration ag",
      properties.field_16,
      " g"
    )}
        ${renderPopupMetric("Scenario " + String(properties.intensity_measure || ""), properties.motion_value, " " + String(properties.motion_units || ""))}
        ${renderPopupMetric("Magnitude Mw", properties.Mw_calc)}
        ${renderPopupMetric("Fault", properties.fault_id)}
        ${renderPopupMetric("Fault name", properties.sourcename)}
        ${renderPopupMetric("Catalogue maximum magnitude", properties.maxmag)}
        ${renderPopupMetric("Catalogue rake", properties.rake, "°")}
        ${renderPopupMetric("Scenario rake", properties.rake_used, "°")}
        ${renderPopupMetric("RJB", properties.RJB_km, " km")}
        ${renderPopupMetric("Vs30", properties.Vs30_1, " m/s")}
        ${properties.Esito_calc ? `<div>${escapeHtml(String(properties.Esito_calc))}</div>` : ''}
      </div>
    `)
    .addTo(currentMap as any);
};

const renderPopupMetric = (
  label: string,
  value?: number | string | null,
  suffix = ""
) => {
  if (
    value === undefined ||
    value === null ||
    value === ""
  ) {
    return "";
  }

  const formatted =
    typeof value === "number"
      ? new Intl.NumberFormat(undefined, {
        maximumFractionDigits: 6
      }).format(value)
      : escapeHtml(String(value));

  return `
    <div style="margin-top: 3px;">
      ${escapeHtml(label)}: <strong>${formatted}${escapeHtml(suffix)}</strong>
    </div>
  `;
};

const handleMouseEnter = () => {
  if (map.value) {
    map.value.getCanvas().style.cursor = "pointer";
  }
};

const handleMouseLeave = () => {
  if (map.value) {
    map.value.getCanvas().style.cursor = "";
  }
};

const extendBoundsWithGeometry = (
  bounds: LngLatBounds,
  geometry: Geometry | null
) => {
  if (!geometry) return;

  switch (geometry.type) {
    case "Point":
      bounds.extend(geometry.coordinates as [number, number]);
      break;

    case "MultiPoint":
    case "LineString":
      for (const coord of geometry.coordinates as [number, number][]) {
        bounds.extend(coord);
      }
      break;

    case "MultiLineString":
    case "Polygon":
      for (const ring of geometry.coordinates as [number, number][][]) {
        for (const coord of ring) {
          bounds.extend(coord);
        }
      }
      break;

    case "MultiPolygon":
      for (const polygon of geometry.coordinates as [number, number][][][]) {
        for (const ring of polygon) {
          for (const coord of ring) {
            bounds.extend(coord);
          }
        }
      }
      break;

    case "GeometryCollection":
      for (const child of geometry.geometries) {
        extendBoundsWithGeometry(bounds, child);
      }
      break;
  }
};

const escapeHtml = (value: string): string => {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
};
</script>

<template>
  <div class="h-full w-full"
    :class="overlay ? 'rounded-none bg-transparent' : 'mt-4 rounded-2xl border border-blue-100 bg-blue-50 p-4'">
    <div v-if="!hideControls" class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h3 class="text-base font-bold text-blue-900">
          Interactive Hazard Map
        </h3>
        <p class="mt-1 text-sm text-blue-800">
          Map layers are generated from the same spatial data used in the report.
        </p>
      </div>

      <select v-model="activeLayerId"
        class="min-w-60 rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm text-gray-800 shadow-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100">
        <option v-for="layer in layers" :key="layer.layer_id" :value="layer.layer_id">
          {{ layer.layer_name }}
        </option>
      </select>
    </div>

    <div class="relative overflow-hidden" :class="overlay ? 'h-full rounded-none' : 'h-[520px] rounded-xl'">
      <div ref="mapContainer" class="h-full w-full" />
      <button v-if="layers.length" type="button" @click="fitToAllLayers"
        class="absolute left-3 top-3 z-10 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow hover:bg-gray-50">
        Zoom to layers
      </button>

      <div v-if="activeLayer && !hideControls"
        class="absolute bottom-4 right-4 z-10 max-h-72 overflow-y-auto min-w-44 rounded-xl border border-gray-200 bg-white p-3 shadow-xl">
        <h4 class="mb-2 text-sm font-bold text-gray-900">
          {{ activeLayer.layer_name }}
        </h4>

        <div v-for="item in activeLayer.legend" :key="item.label"
          class="mb-1.5 flex items-center gap-2 text-xs text-gray-700">
          <span class="h-3.5 w-3.5 rounded border border-gray-300" :style="{ backgroundColor: item.color }" />
          <span>{{ item.label }}</span>
        </div>

        <p v-if="activeLayer.feature_count" class="mt-2 text-xs text-gray-500">
          {{ activeLayer.feature_count }} mapped features
        </p>
      </div>
    </div>
  </div>
</template>
