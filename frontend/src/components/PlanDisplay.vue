<script setup lang="ts">
import type { DisplayPlan } from '@/types/app';
import { computed } from 'vue';

const props = defineProps<{
    plan: DisplayPlan | null;
    showApproval?: boolean;
}>();

const hasContent = computed(() => {
    if (!props.plan) return false;
    return (
        (props.plan.tools?.length || 0) > 0 ||
        (props.plan.spatial_analyses?.length || 0) > 0 ||
        (props.plan.document_searches?.length || 0) > 0 ||
        (props.plan.web_results?.length || 0) > 0
    );
});
</script>

<template>
    <div v-if="plan" class="w-full">
        <div class="mb-4 flex items-center justify-between">
            <h3 class="font-semibold text-gray-800 text-base flex items-center gap-2">
                {{ plan.title || 'Analysis Plan' }}
            </h3>
        </div>

        <div class="space-y-5">
            <div v-if="plan.tools?.length">
                <p class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Data Sources</p>
                <div class="flex flex-wrap gap-2">
                    <span v-for="tool in plan.tools" :key="tool.id"
                        class="px-2.5 py-1 bg-gray-50 border border-gray-200 text-gray-700 text-xs rounded-md shadow-sm">
                        {{ tool.label }}
                    </span>
                </div>
            </div>

            <div v-if="plan.document_searches?.length">
                <p class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Document Queries</p>
                <div class="space-y-3">
                    <div v-for="search in plan.document_searches" :key="search.title"
                        class="bg-gray-50 p-2 rounded border border-gray-100">
                        <p class="font-medium text-gray-700 text-sm mb-1.5 break-all">{{ search.target_file }}</p>
                        <div class="flex flex-wrap gap-1.5">
                            <span v-for="query in search.queries" :key="query"
                                class="text-[11px] bg-orange-50 border border-orange-200 text-orange-700 px-2 py-0.5 rounded-lg">
                                {{ query }}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            <div v-if="plan.spatial_analyses?.length">
                <p class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Spatial Context</p>
                <div class="space-y-3">
                    <div class="bg-gray-50 p-2 rounded border border-gray-100 flex flex-col gap-2"
                        v-for="analysis in plan.spatial_analyses" :key="analysis.title">
                        <div v-if="analysis.hazards?.length" class="flex flex-wrap gap-1.5">
                            <span v-for="hazard in analysis.hazards" :key="hazard.name"
                                class="text-[11px] bg-red-50 border border-red-200 text-red-700 px-2 py-0.5 rounded-full">
                                {{ hazard.name }}
                            </span>
                        </div>
                        <div v-if="analysis.locations?.length" class="flex flex-wrap gap-1.5">
                            <span v-for="location in analysis.locations" :key="location.type + location.name"
                                class="text-[11px] bg-green-50 border border-green-200 text-green-700 px-2 py-0.5 rounded-full">
                                {{ location.name }} {{ location.parent ? `(${location.parent})` : '' }}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            <div v-if="plan.web_results?.length">
                <p class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Web Searches</p>
                <div class="flex flex-col gap-2">
                    <a v-for="res in plan.web_results" :key="res.url" :href="res.url" target="_blank"
                        class="text-sm text-blue-600 hover:text-blue-800 hover:underline truncate bg-blue-50/50 p-1.5 rounded border border-blue-100">
                        {{ res.title || res.url }}
                    </a>
                </div>
            </div>

            <div v-if="!hasContent">
                <p class="text-sm text-gray-500 italic">No analysis plan details available.</p>
            </div>

            <div v-if="showApproval" class="mt-6 pt-4 border-t border-gray-200">
                <p class="text-sm text-gray-600">Reply with <strong class="text-gray-900 font-semibold">"yes"</strong>
                    to approve, or type your requested changes.</p>
            </div>
        </div>
    </div>
</template>