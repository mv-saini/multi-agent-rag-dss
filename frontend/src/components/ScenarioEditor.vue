<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import maplibregl, { type Map as MapInstance, type GeoJSONSource } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { FeatureCollection } from 'geojson'
import { useApiRequest, useHandleApiResponse } from '@/composables/useApi'
import type { ScenarioRequest, ScenarioSelection, SeismicScenario } from '@/types/app'
import { ArrowRight, ChevronDown, MapPin, Scan, Search, SlidersHorizontal, X } from '@lucide/vue'

const props = defineProps<{ request: ScenarioRequest }>()
const emit = defineEmits<{ select: [selection: ScenarioSelection]; close: [] }>()
interface Fault {
  idsource: string
  sourcename: string
  maxmag: number
  rake: number
}
interface Catalogue {
  faults: Fault[]
  geojson: FeatureCollection
  periods: number[]
  max_cells: number
  defaults: Partial<SeismicScenario>
}
const catalogue = ref<Catalogue | null>(null)
const error = ref('')
const query = ref('')
const container = ref<HTMLDivElement | null>(null)
const dialog = ref<HTMLDialogElement | null>(null)
const inputClass =
  'mt-1.5 h-10 w-full rounded-lg border border-gray-200 bg-white px-3 text-sm text-gray-900 outline-none transition-colors placeholder:text-gray-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-50'
let map: MapInstance | null = null
const drawing = ref(false)
const firstCorner = ref<[number, number] | null>(null)
const draft = reactive<Partial<SeismicScenario>>({ ...props.request.draft })
const faults = computed(
  () =>
    catalogue.value?.faults.filter(
      (fault) =>
        fault.idsource === draft.fault_id ||
        `${fault.idsource} ${fault.sourcename}`.toLowerCase().includes(query.value.toLowerCase()),
    ) ?? [],
)
const selectedFault = computed(() =>
  catalogue.value?.faults.find((f) => f.idsource === draft.fault_id),
)
const selectedFaultId = computed({
  get: () => draft.fault_id ?? '',
  set: (id: string) => selectFault(id),
})

function selectFault(id: string) {
  draft.fault_id = id
  if (draft.magnitude == null) draft.magnitude = selectedFault.value?.maxmag
  if (map?.getLayer('selected-fault'))
    map.setFilter('selected-fault', ['==', ['get', 'idsource'], id])
}

function updateBox() {
  const bbox = draft.area_mode === 'bbox' ? draft.bbox : null
  const source = map?.getSource('area') as GeoJSONSource | undefined
  if (draft.area_mode === 'bbox' && drawing.value && firstCorner.value) {
    source?.setData({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: {},
          geometry: { type: 'Point', coordinates: firstCorner.value },
        },
      ],
    })
    return
  }
  source?.setData({
    type: 'FeatureCollection',
    features: bbox
      ? [
        {
          type: 'Feature',
          properties: {},
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [bbox[0], bbox[1]],
                [bbox[2], bbox[1]],
                [bbox[2], bbox[3]],
                [bbox[0], bbox[3]],
                [bbox[0], bbox[1]],
              ],
            ],
          },
        },
      ]
      : [],
  })
}

function clearInactiveAreaParameters() {
  if (draft.area_mode !== 'fault_buffer') draft.buffer_km = null
  else if (draft.buffer_km == null) draft.buffer_km = catalogue.value?.defaults.buffer_km ?? null
  if (draft.area_mode !== 'bbox') draft.bbox = null
}

watch(
  () => draft.area_mode,
  () => {
    clearInactiveAreaParameters()
    drawing.value = false
    firstCorner.value = null
    if (map) map.getCanvas().style.cursor = ''
    updateBox()
  },
  { flush: 'sync' },
)

function startAreaSelection() {
  draft.area_mode = 'bbox'
  firstCorner.value = null
  draft.bbox = null
  drawing.value = true
  updateBox()
  if (map) map.getCanvas().style.cursor = 'crosshair'
}

function submit() {
  error.value = ''
  if (drawing.value) {
    error.value = 'Finish selecting the area by choosing two opposite corners on the map.'
    return
  }
  if (!selectedFault.value) {
    error.value = 'Select a fault on the map or from the list.'
    return
  }
  if (draft.magnitude == null || !Number.isFinite(Number(draft.magnitude))) {
    error.value = 'Enter a finite magnitude.'
    return
  }
  if (!Number.isFinite(Number(draft.resolution_m)) || Number(draft.resolution_m) <= 0) {
    error.value = 'Resolution must be positive.'
    return
  }
  if (draft.area_mode === 'fault_buffer' &&
    (!Number.isFinite(Number(draft.buffer_km)) || Number(draft.buffer_km) <= 0)) {
    error.value = 'Buffer must be positive.'
    return
  }
  if (
    ![draft.grid_origin_x, draft.grid_origin_y].every(
      (n) => n != null && String(n) !== '' && Number.isFinite(Number(n)),
    )
  ) {
    error.value = 'Enter finite grid origin coordinates.'
    return
  }
  if (
    draft.rake != null &&
    String(draft.rake) !== '' &&
    (!Number.isFinite(Number(draft.rake)) || Number(draft.rake) < 0 || Number(draft.rake) > 360)
  ) {
    error.value = 'Rake must be between 0 and 360 degrees.'
    return
  }
  if (
    draft.vs30_override != null &&
    String(draft.vs30_override) !== '' &&
    (!Number.isFinite(Number(draft.vs30_override)) || Number(draft.vs30_override) <= 0)
  ) {
    error.value = 'Vs30 must be positive.'
    return
  }
  if (draft.area_mode === 'bbox' && !draft.bbox) {
    error.value = 'Choose two opposite corners on the map.'
    return
  }
  if (
    draft.intensity_measure === 'SA' &&
    !catalogue.value?.periods.includes(Number(draft.period_s))
  ) {
    error.value = 'Select a supported spectral period.'
    return
  }
  emit('select', {
    scenario: {
      fault_id: draft.fault_id!,
      magnitude: Number(draft.magnitude),
      resolution_m: Number(draft.resolution_m),
      intensity_measure: draft.intensity_measure!,
      period_s: draft.intensity_measure === 'SA' ? Number(draft.period_s) : null,
      area_mode: draft.area_mode!,
      buffer_km: draft.area_mode === 'fault_buffer' ? Number(draft.buffer_km) : null,
      bbox: draft.area_mode === 'bbox' ? draft.bbox ?? null : null,
      rake: draft.rake == null || String(draft.rake) === '' ? null : Number(draft.rake),
      vs30_override:
        draft.vs30_override == null || String(draft.vs30_override) === ''
          ? null
          : Number(draft.vs30_override),
      grid_origin_x: Number(draft.grid_origin_x),
      grid_origin_y: Number(draft.grid_origin_y),
    },
  })
}

onMounted(async () => {
  dialog.value?.showModal()
  try {
    catalogue.value = useHandleApiResponse(await useApiRequest<Catalogue>('/api/seismic/faults'))
    Object.assign(draft, {
      ...catalogue.value.defaults,
      area_mode: 'bbox',
      ...props.request.draft,
    })
    // Old saved requests may still contain the removed administrative mode.
    if (draft.area_mode !== 'bbox' && draft.area_mode !== 'fault_buffer') draft.area_mode = 'bbox'
    clearInactiveAreaParameters()
    if (draft.period_s == null) draft.period_s = catalogue.value.defaults.period_s
    if (!container.value) return
    map = new maplibregl.Map({
      container: container.value,
      center: [12.5, 42.5],
      zoom: 5,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors',
          },
        },
        layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
      },
    })
    map.addControl(new maplibregl.NavigationControl())
    map.on('load', () => {
      if (!map || !catalogue.value) return
      map.addSource('faults', { type: 'geojson', data: catalogue.value.geojson })
      map.addLayer({
        id: 'fault-fill',
        source: 'faults',
        type: 'fill',
        paint: { 'fill-color': '#b45309', 'fill-opacity': 0.35 },
      })
      map.addLayer({
        id: 'fault-line',
        source: 'faults',
        type: 'line',
        paint: { 'line-color': '#92400e', 'line-width': 2 },
      })
      map.addLayer({
        id: 'selected-fault',
        source: 'faults',
        type: 'line',
        filter: ['==', ['get', 'idsource'], draft.fault_id ?? ''],
        paint: { 'line-color': '#2563eb', 'line-width': 5 },
      })
      map.addSource('area', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addLayer({
        id: 'area-line',
        source: 'area',
        type: 'line',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'line-color': '#059669', 'line-width': 3 },
      })
      map.addLayer({
        id: 'area-corner',
        source: 'area',
        type: 'circle',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-radius': 7,
          'circle-color': '#059669',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 3,
        },
      })
      updateBox()
      if (draft.fault_id) selectFault(draft.fault_id)
    })
    map.on('click', (event) => {
      if (!map?.isStyleLoaded()) return
      if (drawing.value) {
        if (!firstCorner.value) {
          firstCorner.value = [event.lngLat.lng, event.lngLat.lat]
          updateBox()
          return
        }
        draft.bbox = [
          Math.min(firstCorner.value[0], event.lngLat.lng),
          Math.min(firstCorner.value[1], event.lngLat.lat),
          Math.max(firstCorner.value[0], event.lngLat.lng),
          Math.max(firstCorner.value[1], event.lngLat.lat),
        ]
        drawing.value = false
        firstCorner.value = null
        map.getCanvas().style.cursor = ''
        updateBox()
      } else {
        const feature = map.queryRenderedFeatures(event.point, {
          layers: ['fault-fill', 'fault-line'],
        })[0]
        if (feature?.properties?.idsource) selectFault(String(feature.properties.idsource))
      }
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Unable to load faults.'
  }
})
onBeforeUnmount(() => {
  dialog.value?.close()
  map?.remove()
  map = null
})
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" aria-labelledby="scenario-title" @cancel.prevent="emit('close')"
      class="fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none overflow-hidden rounded-none border-0 bg-white p-0 text-gray-900 open:flex open:flex-col">
      <header class="flex shrink-0 items-center justify-between gap-4 border-b border-gray-100 px-5 py-4">
        <div class="flex items-center gap-3">
          <span class="flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 text-gray-600">
            <SlidersHorizontal class="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h2 id="scenario-title" class="text-base font-semibold">Earthquake scenario</h2>
            <p class="mt-0.5 text-xs text-gray-500">
              Choose your inputs. Calculation starts after you approve the plan.
            </p>
          </div>
        </div>
        <button type="button" aria-label="Close scenario editor" autofocus
          class="shrink-0 rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 focus-visible:ring-2 focus-visible:ring-blue-500"
          @click="emit('close')">
          <X class="h-5 w-5" aria-hidden="true" />
        </button>
      </header>

      <div class="min-h-0 flex-1 overflow-y-auto md:flex md:overflow-hidden">
        <div class="relative h-64 bg-gray-50 md:h-auto md:min-w-0 md:flex-1">
          <div ref="container" class="h-full w-full" aria-label="Fault selection map" />
          <div
            class="pointer-events-none absolute left-4 top-4 max-w-[calc(100%-5rem)] rounded-lg border border-gray-200 bg-white/95 px-3 py-2 shadow-sm">
            <p class="flex items-center gap-2 text-xs font-medium text-gray-700">
              <MapPin class="h-3.5 w-3.5" aria-hidden="true" />{{
                drawing
                  ? firstCorner
                    ? 'First corner selected. Click the opposite corner.'
                    : 'Click the first corner of your area'
                  : 'Click a fault to select it'
              }}
            </p>
          </div>
          <div v-if="selectedFault"
            class="pointer-events-none absolute bottom-5 left-4 right-4 rounded-lg border border-gray-200 bg-white/95 px-3.5 py-3 shadow-sm">
            <div class="flex items-center gap-2">
              <span class="h-2 w-2 rounded-full bg-blue-600" />
              <p class="text-sm font-medium text-gray-900">{{ selectedFault.sourcename }}</p>
            </div>
            <p class="mt-1 pl-4 text-xs text-gray-500">
              {{ selectedFault.idsource }} · Catalogue Mw {{ selectedFault.maxmag }} · Rake
              {{ selectedFault.rake }}°
            </p>
          </div>
        </div>

        <form id="scenario-parameters"
          class="w-full shrink-0 divide-y divide-gray-100 border-t border-gray-100 md:w-96 md:overflow-y-auto md:border-l md:border-t-0"
          @submit.prevent="submit">
          <section class="space-y-4 px-5 py-5">
            <div>
              <h3 class="text-sm font-semibold">Fault</h3>
              <p class="mt-1 text-xs text-gray-500">Select on the map or search the catalogue.</p>
            </div>
            <p v-if="!catalogue && !error" role="status" class="text-xs text-gray-500">
              Loading fault catalogue…
            </p>
            <label class="block text-xs font-medium text-gray-600">Search faults
              <span class="relative block">
                <Search class="pointer-events-none absolute left-3 top-4 h-4 w-4 text-gray-400" aria-hidden="true" />
                <input v-model="query" :class="[inputClass, 'pl-9']" placeholder="Name or source ID" />
              </span>
            </label>
            <label class="block text-xs font-medium text-gray-600">Selected fault
              <select v-model="selectedFaultId" required :class="inputClass">
                <option value="" disabled>Choose a fault</option>
                <option v-for="fault in faults" :key="fault.idsource" :value="fault.idsource">
                  {{ fault.idsource }} · {{ fault.sourcename }}
                </option>
              </select>
            </label>
          </section>

          <section class="space-y-4 px-5 py-5">
            <h3 class="text-sm font-semibold">Shaking parameters</h3>
            <div class="grid grid-cols-2 gap-3">
              <label class="block text-xs font-medium text-gray-600">Magnitude · Mw<input
                  v-model.number="draft.magnitude" type="number" step="any" required :class="inputClass" /></label>
              <label class="block text-xs font-medium text-gray-600">Grid size · m<input
                  v-model.number="draft.resolution_m" type="number" min="0.001" step="any" required
                  :class="inputClass" /></label>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <label class="block text-xs font-medium text-gray-600">Intensity measure<select
                  v-model="draft.intensity_measure" :class="inputClass">
                  <option>PGA</option>
                  <option>PGV</option>
                  <option>SA</option>
                </select></label>
              <label v-if="draft.intensity_measure === 'SA'" class="block text-xs font-medium text-gray-600">Period ·
                s<select v-model.number="draft.period_s" :class="inputClass">
                  <option v-for="period in catalogue?.periods" :key="period" :value="period">
                    {{ period }}
                  </option>
                </select></label>
            </div>
            <p class="text-xs leading-relaxed text-gray-500">
              Hypothetical magnitudes are allowed. The full selected fault polygon is used at every
              magnitude.
            </p>
          </section>

          <section class="space-y-4 px-5 py-5">
            <h3 class="text-sm font-semibold">Analysis area</h3>
            <label class="block text-xs font-medium text-gray-600">Extent<select v-model="draft.area_mode"
                :class="inputClass">
                <option value="fault_buffer">Buffer around the fault</option>
                <option value="bbox">Area selected on map</option>
              </select></label>
            <label v-if="draft.area_mode === 'fault_buffer'" class="block text-xs font-medium text-gray-600">Distance
              from rupture · km<input v-model.number="draft.buffer_km" type="number" step="any" min="0.001" required
                :class="inputClass" /><span class="mt-2 block font-normal leading-relaxed text-gray-500">Shaking may
                extend beyond this calculation area.</span></label>
            <div v-if="draft.area_mode === 'bbox'" class="space-y-2">
              <button type="button"
                class="flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-gray-200 text-sm text-gray-700 transition-colors hover:bg-gray-50"
                @click="startAreaSelection">
                <Scan class="h-4 w-4" aria-hidden="true" />{{
                  drawing
                    ? firstCorner
                      ? 'Choose the opposite corner'
                      : 'Choose the first corner'
                    : 'Select area on map'
                }}
              </button>
              <p v-if="draft.bbox" class="text-xs tabular-nums text-gray-500">
                {{draft.bbox.map((n) => n.toFixed(4)).join(', ')}}
              </p>
            </div>
          </section>

          <details class="group px-5 py-4">
            <summary
              class="flex cursor-pointer list-none items-center justify-between text-sm font-medium text-gray-700 [&::-webkit-details-marker]:hidden">
              Advanced parameters
              <ChevronDown class="h-4 w-4 text-gray-400 transition-transform group-open:rotate-180"
                aria-hidden="true" />
            </summary>
            <div class="mt-4 space-y-4">
              <label class="block text-xs font-medium text-gray-600">Rake override · 0–360°<input
                  v-model.number="draft.rake" type="number" min="0" max="360" step="any" placeholder="Use catalogue"
                  :class="inputClass" /></label>
              <label class="block text-xs font-medium text-gray-600">Uniform Vs30 · m/s<input
                  v-model.number="draft.vs30_override" type="number" min="0.001" step="any"
                  placeholder="Sample Vs30 raster" :class="inputClass" /></label>
              <div class="grid grid-cols-2 gap-3">
                <label class="block text-xs font-medium text-gray-600">Origin easting · m<input
                    v-model.number="draft.grid_origin_x" type="number" step="any" required
                    :class="inputClass" /></label>
                <label class="block text-xs font-medium text-gray-600">Origin northing · m<input
                    v-model.number="draft.grid_origin_y" type="number" step="any" required
                    :class="inputClass" /></label>
              </div>
              <p class="text-xs leading-relaxed text-gray-500">
                Lanzano 2019 · median RotD50. PGA/SA in g; PGV in cm/s. Maximum grid:
                {{ catalogue?.max_cells?.toLocaleString() }} cells.
              </p>
            </div>
          </details>
        </form>
      </div>

      <footer class="shrink-0 border-t border-gray-100 bg-white px-5 py-4">
        <p v-if="error" role="alert"
          class="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {{ error }}
        </p>
        <div class="flex items-center justify-between gap-3">
          <div class="ml-auto flex items-center gap-2">
            <button type="button" class="h-9 rounded-md px-3 text-sm text-gray-600 transition-colors hover:bg-gray-100"
              @click="emit('close')">
              Back to chat
            </button>
            <button type="submit" form="scenario-parameters" :disabled="!catalogue"
              class="inline-flex h-9 items-center gap-2 rounded-md bg-gray-900 px-4 text-sm font-medium text-white transition-colors hover:bg-gray-700 disabled:cursor-wait disabled:opacity-50">
              Use parameters
              <ArrowRight class="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      </footer>
    </dialog>
  </Teleport>
</template>
