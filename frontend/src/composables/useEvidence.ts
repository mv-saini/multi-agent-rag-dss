import { computed, onScopeDispose, ref, shallowRef, type Ref } from 'vue';
import type { EvidenceBundle, HazardMapLayer } from '@/types/app';
import { useApiRequest, useHandleApiResponse } from './useApi';

export function useEvidence(threadId: Ref<string | null>) {
  const bundles = shallowRef<Record<string, EvidenceBundle>>({});
  const bundleIds = ref<string[]>([]);
  const activeMapLayerIds = ref<string[]>([]);
  const error = ref('');
  const pending = new Map<string, Promise<void>>();
  let generation = 0;
  let requestController = new AbortController();
  onScopeDispose(() => requestController.abort());
  const loading = ref(false);

  const mapLayers = computed(() => {
    const layers = new Map<string, HazardMapLayer>();
    for (const id of bundleIds.value) {
      for (const layer of bundles.value[id]?.map_layers ?? []) {
        layers.set(layer.layer_id, layer);
      }
    }
    return Array.from(layers.values());
  });

  function reset() {
    generation += 1;
    requestController.abort();
    requestController = new AbortController();
    bundles.value = {};
    bundleIds.value = [];
    activeMapLayerIds.value = [];
    error.value = '';
    pending.clear();
    loading.value = false;
  }

  async function load(bundleId: string): Promise<void> {
    const owner = threadId.value;
    if (!owner) return;
    if (!bundleIds.value.includes(bundleId)) bundleIds.value.push(bundleId);
    if (bundles.value[bundleId]) return;
    if (pending.has(bundleId)) return pending.get(bundleId)!;
    const requestGeneration = generation;
    const request = (async () => {
      try {
        loading.value = true;
        const response = await useApiRequest<EvidenceBundle>(
          '/api/threads/' + encodeURIComponent(owner) + '/evidence/' + encodeURIComponent(bundleId),
          { signal: requestController.signal },
        );
        const bundle = useHandleApiResponse(response);
        if (generation !== requestGeneration || threadId.value !== owner) return;
        bundles.value = { ...bundles.value, [bundleId]: bundle };
        activeMapLayerIds.value = [];
      } catch (cause) {
        if (generation === requestGeneration && threadId.value === owner) {
          error.value = cause instanceof Error ? cause.message : 'Unable to load evidence.';
        }
      } finally {
        if (generation === requestGeneration) {
          pending.delete(bundleId);
          loading.value = pending.size > 0;
        }
      }
    })();
    pending.set(bundleId, request);
    return request;
  }

  async function loadAll(ids: string[]) {
    const requestGeneration = generation;
    for (let start = 0; start < ids.length; start += 4) {
      if (generation !== requestGeneration) return;
      await Promise.all(ids.slice(start, start + 4).map(load));
    }
  }

  async function retry() {
    error.value = '';
    await loadAll([...bundleIds.value]);
  }

  return { bundles, mapLayers, loading, activeMapLayerIds, error, reset, load, loadAll, retry };
}
