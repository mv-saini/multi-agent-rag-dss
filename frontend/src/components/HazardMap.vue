<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import maplibregl, {
  LngLatBounds,
  Map,
  Popup
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Geometry } from "geojson";
import type { HazardMapLayer } from "@/types/app";

const props = defineProps<{
  layers: HazardMapLayer[];
  overlay?: boolean;
  hideControls?: boolean;
}>();

const mapContainer = ref<HTMLDivElement | null>(null);
const map = ref<Map | null>(null);
const popup = ref<Popup | null>(null);

const activeLayerId = ref<string>("");

const managedLayerIds = ref<string[]>([]);
const managedSourceIds = ref<string[]>([]);

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
  () => props.layers,
  async () => {
    await nextTick();

    if (!map.value) {
      initMap();
      return;
    }

    updateMapLayer();
  },
  { deep: true, immediate: true }
);

watch(activeLayerId, () => {
  updateMapLayer();
});

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
    updateMapLayer();
  });
};

const updateMapLayer = () => {
  if (!map.value || !map.value.isStyleLoaded()) {
    return;
  }

  clearManagedLayers();

  for (const layer of props.layers) {
    if (!layer.geojson || layer.empty) continue;

    addHazardLayer(layer);
  }

  fitToAllLayers();
};

const fitToAllLayers = () => {
  if (!map.value || !props.layers.length) return;

  const bounds = new maplibregl.LngLatBounds();

  for (const layer of props.layers) {
    if (!layer.geojson?.features?.length) continue;

    for (const feature of layer.geojson.features) {
      extendBoundsWithGeometry(bounds, feature.geometry);
    }
  }

  if (!bounds.isEmpty()) {
    map.value.fitBounds(bounds, {
      padding: 40,
      maxZoom: 13,
      duration: 500
    });
  }
};

const safeId = (value: string) => {
  return value.replace(/[^a-zA-Z0-9_-]/g, "_");
};

const addHazardLayer = (hazardLayer: HazardMapLayer) => {
  if (!map.value) return;

  const currentMap = map.value;

  const sourceId = `hazard-source-${safeId(hazardLayer.layer_id)}`;
  const fillLayerId = `hazard-fill-${safeId(hazardLayer.layer_id)}`;
  const outlineLayerId = `hazard-outline-${safeId(hazardLayer.layer_id)}`;
  const pointLayerId = `hazard-point-${safeId(hazardLayer.layer_id)}`;

  currentMap.addSource(sourceId, {
    type: "geojson",
    data: hazardLayer.geojson
  });

  managedSourceIds.value.push(sourceId);

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
      "fill-color": ["coalesce", ["get", "risk_color"], "#9e9e9e"],
      "fill-opacity": 0.45
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
      "line-color": "#000000",
      "line-width": 1
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
      "circle-radius": hazardLayer.hazard_name?.toLowerCase() === 'seismic' ? 5 : 3,
      "circle-color": ["coalesce", ["get", "risk_color"], "#9e9e9e"],
      "circle-opacity": 0.45,
      "circle-stroke-color": "#000000",
      "circle-stroke-width": 1
    }
  });

  for (const mapLayerId of [fillLayerId, outlineLayerId, pointLayerId]) {
    managedLayerIds.value.push(mapLayerId);

    currentMap.on("click", mapLayerId, event => {
      handleFeatureClick(event, hazardLayer);
    });

    currentMap.on("mouseenter", mapLayerId, handleMouseEnter);
    currentMap.on("mouseleave", mapLayerId, handleMouseLeave);
  }
};

const clearManagedLayers = () => {
  if (!map.value) return;

  const currentMap = map.value;

  for (const layerId of [...managedLayerIds.value].reverse()) {
    if (currentMap.getLayer(layerId)) {
      currentMap.removeLayer(layerId);
    }
  }

  for (const sourceId of managedSourceIds.value) {
    if (currentMap.getSource(sourceId)) {
      currentMap.removeSource(sourceId);
    }
  }

  managedLayerIds.value = [];
  managedSourceIds.value = [];
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

  const riskLabel = properties.risk_label || "Unclassified";

  if (popup.value) {
    popup.value.remove();
  }

  popup.value = new maplibregl.Popup()
    .setLngLat(event.lngLat)
    .setHTML(`
      <div style="min-width: 240px">
        <strong>${escapeHtml(hazardLayer.layer_name)}</strong><br />
        <div style="margin-top: 4px;">
          Risk: <strong>${escapeHtml(String(riskLabel))}</strong>
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
    value === "" ||
    Number(value) === 0
  ) {
    return "";
  }

  const formatted =
    typeof value === "number"
      ? new Intl.NumberFormat(undefined, {
        maximumFractionDigits: 2
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

      <div v-if="activeLayer && !hideControls"
        class="absolute bottom-4 right-4 z-10 min-w-44 rounded-xl border border-gray-200 bg-white p-3 shadow-xl">
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