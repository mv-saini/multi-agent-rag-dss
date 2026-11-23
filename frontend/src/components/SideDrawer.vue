<script setup lang="ts">
import { ref, computed } from 'vue';
import { vMarkdown } from '../directives/markdown';
import { renderMarkdown } from '../utils/markdown';
import PlanDisplay from './PlanDisplay.vue';
import type { DisplayPlan } from '../types/app.ts';
import { Check, Copy, FileText, X } from '@lucide/vue';

const props = defineProps<{
    isOpen: boolean;
    type: 'plan' | 'context' | null;
    planData: DisplayPlan | null;
    contextData: Record<string, string> | null;
}>();

const emit = defineEmits<{ (e: 'close'): void }>();

const PREFERRED_ORDER = ['spatial_analysis', 'vector_docs', 'web_results'];

const sortedContext = computed(() => {
    if (!props.contextData) return [];

    return Object.entries(props.contextData).sort(([keyA], [keyB]) => {
        const indexA = PREFERRED_ORDER.indexOf(keyA);
        const indexB = PREFERRED_ORDER.indexOf(keyB);

        if (indexA !== -1 && indexB !== -1) return indexA - indexB;
        if (indexA !== -1) return -1;
        if (indexB !== -1) return 1;

        return keyA.localeCompare(keyB);
    });
});

const isContextCopied = ref(false);

const copyContext = async () => {
    if (!sortedContext.value.length) return;

    let textToCopy = '';
    for (const [source, content] of sortedContext.value) {
        textToCopy += `### ${source}\n${content}\n\n`;
    }

    try {
        await navigator.clipboard.writeText(textToCopy.trim());
        isContextCopied.value = true;

        setTimeout(() => {
            isContextCopied.value = false;
        }, 2000);
    } catch (err) {
        console.error('Failed to copy context', err);
    }
};
</script>

<template>
    <div>
        <div v-show="isOpen" class="fixed inset-0 bg-black/20 z-40 transition-opacity" @click="emit('close')"></div>

        <div class="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-white shadow-2xl transform transition-transform duration-300 ease-in-out flex flex-col"
            :class="isOpen ? 'translate-x-0' : 'translate-x-full'">

            <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gray-50/50">
                <div>
                    <h2 class="text-lg font-semibold text-gray-800">
                        {{ type === 'plan' ? 'Execution Plan' : 'Retrieved Context' }}
                    </h2>
                </div>

                <div class="flex items-center gap-2">
                    <button v-if="type === 'context'" @click="copyContext"
                        class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors shadow-sm"
                        :class="isContextCopied ? 'bg-green-100 text-green-700 border border-green-200' : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'">

                        <Copy v-if="!isContextCopied" class="h-3.5 w-3.5" aria-hidden="true" />
                        <Check v-else class="h-3.5 w-3.5" aria-hidden="true" />

                        <span>{{ isContextCopied ? 'Copied!' : 'Copy' }}</span>
                    </button>

                    <button @click="emit('close')"
                        class="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-200 rounded-full transition-colors">
                        <X class="h-5 w-5" aria-hidden="true" />
                    </button>
                </div>
            </div>

            <div class="flex-1 overflow-y-auto p-6">
                <PlanDisplay v-if="type === 'plan'" :plan="planData" :showApproval="false" />

                <div v-if="type === 'context'" class="space-y-6">
                    <div v-for="([source, content]) in sortedContext" :key="source"
                        class="border border-gray-200 rounded-lg overflow-hidden">
                        <div class="bg-gray-100 px-4 py-2 border-b border-gray-200 flex items-center gap-2">
                            <FileText class="h-4 w-4 text-gray-500" aria-hidden="true" />
                            <h4 class="text-sm font-semibold text-gray-700 truncate" :title="source">{{ source }}</h4>
                        </div>
                        <div class="p-4 bg-white">
                            <div class="prose prose-sm max-w-none text-gray-600 text-sm"
                                v-markdown="renderMarkdown(content)"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>