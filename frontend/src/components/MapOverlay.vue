<script setup lang="ts">
import { computed } from 'vue';
import { X } from '@lucide/vue';
import HazardMap from "./HazardMap.vue";
import type { HazardMapLayer } from '../types/app.ts';

const props = defineProps<{
    show: boolean;
    layers: HazardMapLayer[];
    activeLayerIds: string[];
}>();

const emit = defineEmits<{
    (e: 'close'): void;
    (e: 'update:activeLayers', ids: string[]): void;
}>();

const activeLayers = computed(() => props.layers.filter(layer => props.activeLayerIds.includes(layer.layer_id)));

const toggleLayer = (layerId: string) => {
    const newIds = props.activeLayerIds.includes(layerId)
        ? props.activeLayerIds.filter(id => id !== layerId)
        : [...props.activeLayerIds, layerId];
    emit('update:activeLayers', newIds);
};

const selectAll = () => emit('update:activeLayers', props.layers.map(l => l.layer_id));
const clearAll = () => emit('update:activeLayers', []);

const formatNumber = (value?: number | null) => value == null ? "—" : new Intl.NumberFormat().format(value);
const formatArea = (value?: number | null) => value == null ? "—" : `${value.toFixed(2)} km²`;
const formatPercent = (value?: number | null) => value == null ? "—" : `${value.toFixed(1)}%`;
</script>

<template>
    <div v-if="show" class="fixed inset-0 z-50 flex h-screen w-screen bg-white">
        <div class="flex h-full w-full flex-col overflow-hidden">
            <div class="flex items-start justify-between border-b border-gray-200 bg-gray-50 px-6 py-5">
                <div>
                    <p class="text-xs font-semibold uppercase tracking-widest text-blue-600">Spatial analysis</p>
                    <h2 class="mt-1 text-xl font-semibold text-gray-900">Interactive Map</h2>
                    <p class="mt-1 text-sm text-gray-500">Generated from the same spatial data used in the report.</p>
                </div>
                <button @click="emit('close')" aria-label="Close map"
                    class="flex h-9 w-9 items-center justify-center rounded-lg text-gray-400 hover:bg-white hover:text-gray-700">
                    <X class="h-5 w-5" aria-hidden="true" />
                </button>
            </div>

            <div class="flex flex-1 min-h-0">
                <aside class="w-96 shrink-0 border-r border-gray-200 bg-gray-50 p-4 overflow-y-auto">
                    <div class="mb-4 flex items-center justify-between gap-2">
                        <div>
                            <h3 class="font-semibold text-gray-900">Hazard layers</h3>
                            <p class="text-xs text-gray-500">Toggle one or more hazards on the map.</p>
                        </div>
                        <div class="flex gap-2">
                            <button @click="selectAll"
                                class="rounded-md bg-blue-100 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-200">All</button>
                            <button @click="clearAll"
                                class="rounded-md bg-gray-200 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-300">None</button>
                        </div>
                    </div>

                    <div class="space-y-3">
                        <div v-for="layer in layers" :key="layer.layer_id"
                            class="rounded-xl border bg-white p-3 shadow-sm"
                            :class="activeLayerIds.includes(layer.layer_id) ? 'border-blue-300 ring-1 ring-blue-100' : 'border-gray-200'">

                            <label class="flex cursor-pointer items-start gap-3">
                                <input type="checkbox" class="mt-1 h-4 w-4 rounded text-blue-600"
                                    :checked="activeLayerIds.includes(layer.layer_id)"
                                    @change="toggleLayer(layer.layer_id)" />
                                <div class="min-w-0 flex-1">
                                    <div class="font-medium text-gray-900">{{ layer.layer_name }}</div>
                                    <div class="mt-1 text-xs text-gray-500">{{ layer.feature_count || 0 }} features
                                    </div>
                                </div>
                            </label>

                            <div v-if="layer.summary_metrics" class="mt-3 grid grid-cols-2 gap-2">
                                <div v-if="layer.summary_metrics.geometry_type" class="rounded-lg bg-gray-50 p-2">
                                    <div class="text-[11px] uppercase tracking-wide text-gray-500">Geometry</div>
                                    <div class="text-sm font-semibold text-gray-900">{{
                                        layer.summary_metrics.geometry_type }}</div>
                                </div>
                                <div v-if="layer.summary_metrics.total_points !== undefined"
                                    class="rounded-lg bg-gray-50 p-2">
                                    <div class="text-[11px] uppercase tracking-wide text-gray-500">Hazard points</div>
                                    <div class="text-sm font-semibold text-gray-900">{{
                                        formatNumber(layer.summary_metrics.total_points) }}</div>
                                </div>
                                <div v-if="layer.summary_metrics.estimated_grid_resolution_meters !== undefined"
                                    class="rounded-lg bg-gray-50 p-2">
                                    <div class="text-[11px] uppercase tracking-wide text-gray-500">
                                        Grid resolution
                                    </div>
                                    <div class="text-sm font-semibold text-gray-900">
                                        {{ layer.summary_metrics.estimated_grid_resolution_meters }} m
                                    </div>
                                </div>

                                <div v-if="layer.summary_metrics.max_intensity_recorded !== undefined"
                                    class="rounded-lg bg-gray-50 p-2">
                                    <div class="text-[11px] uppercase tracking-wide text-gray-500">
                                        Max intensity
                                    </div>
                                    <div class="text-sm font-semibold text-gray-900">
                                        {{ formatNumber(layer.summary_metrics.max_intensity_recorded) }}
                                    </div>
                                </div>
                            </div>

                            <details v-if="layer.risk_breakdown?.length" class="mt-3">
                                <summary class="cursor-pointer text-sm font-medium text-blue-700">Risk breakdown
                                </summary>
                                <div class="mt-2 space-y-2">
                                    <div v-for="risk in layer.risk_breakdown" :key="risk.risk_label"
                                        class="rounded-lg border bg-gray-50 p-2">
                                        <div class="font-medium text-gray-800">{{ risk.risk_label }}</div>
                                        <div v-if="risk.has_data === false" class="mt-1 text-xs text-gray-500">No
                                            features recorded.</div>
                                        <template v-else>
                                            <div v-if="risk.exposed_population !== undefined"
                                                class="mt-1 text-xs text-gray-600">
                                                Population: {{ formatNumber(risk.exposed_population) }}
                                            </div>
                                            <div v-if="risk.exposed_residential_buildings !== undefined"
                                                class="text-xs text-gray-600">
                                                Buildings: {{ formatNumber(risk.exposed_residential_buildings) }}
                                            </div>
                                            <div v-if="risk.exposed_residential_houses !== undefined"
                                                class="text-xs text-gray-600">
                                                Houses: {{ formatNumber(risk.exposed_residential_houses) }}
                                            </div>
                                            <div v-if="risk.exposed_families !== undefined"
                                                class="text-xs text-gray-600">
                                                Families: {{ formatNumber(risk.exposed_families) }}
                                            </div>
                                            <div v-if="risk.affected_area_sqkm !== undefined"
                                                class="text-xs text-gray-600">
                                                Area: {{ formatArea(risk.affected_area_sqkm) }}
                                            </div>
                                            <div v-if="risk.percent_of_territory !== undefined"
                                                class="text-xs text-gray-600">
                                                Territory: {{ formatPercent(risk.percent_of_territory) }}
                                            </div>
                                            <div v-if="risk.point_count !== undefined" class="text-xs text-gray-600">
                                                Points: {{ formatNumber(risk.point_count) }}
                                            </div>
                                        </template>
                                    </div>
                                </div>
                            </details>

                        </div>
                    </div>
                </aside>

                <main class="min-w-0 flex-1">
                    <HazardMap :layers="activeLayers" overlay hide-controls />
                </main>
            </div>
        </div>
    </div>
</template>