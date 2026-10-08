<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { FileText, LoaderCircle, PanelRightClose, PanelRightOpen, RefreshCw, Search } from '@lucide/vue';

interface IndexedDocument {
    id: number;
    filename: string;
}

const props = defineProps<{ isOpen: boolean }>();
const emit = defineEmits<{
    (event: 'close'): void;
    (event: 'open'): void;
}>();

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const documents = ref<IndexedDocument[]>([]);
const searchQuery = ref('');
const isLoading = ref(false);
const errorMessage = ref('');

const filteredDocuments = computed(() => {
    const query = searchQuery.value.trim().toLowerCase();
    if (!query) return documents.value;

    return documents.value.filter(document =>
        `${document.filename}`.toLowerCase().includes(query),
    );
});

const loadDocuments = async () => {
    isLoading.value = true;
    errorMessage.value = '';

    try {
        const response = await fetch(`${API_BASE}/api/documents`);
        if (!response.ok) throw new Error(`Document request failed (${response.status})`);

        const data = await response.json();
        documents.value = data.documents || [];
    } catch (error) {
        errorMessage.value = error instanceof Error
            ? error.message
            : 'Unable to load indexed documents.';
    } finally {
        isLoading.value = false;
    }
};

onMounted(loadDocuments);
</script>

<template>
    <aside v-if="props.isOpen"
        class="fixed inset-y-0 right-0 z-50 flex h-full w-[min(20rem,calc(100vw-2rem))] shrink-0 flex-col overflow-hidden rounded-l-xl bg-white shadow-xl lg:static lg:z-auto lg:w-72 lg:rounded-xl lg:shadow-none"
        aria-label="Indexed documents">
        <header class="flex items-center justify-between px-3 py-2">
            <button
                class="flex h-9 w-9 items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
                aria-label="Close indexed documents" @click="emit('close')">
                <PanelRightClose class="h-5 w-5" aria-hidden="true" />
            </button>
            <div class="text-right">
                <h2 class="text-lg font-semibold text-gray-800">Indexed documents</h2>
            </div>
        </header>

        <div class="border-b border-gray-100 bg-gray-50/60 px-6 py-4">
            <div class="flex gap-2">
                <label class="relative flex-1">
                    <Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
                        aria-hidden="true" />
                    <span class="sr-only">Search indexed documents</span>
                    <input v-model="searchQuery" type="search" placeholder="Search documents"
                        class="w-full rounded-lg border border-gray-300 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" />
                </label>
                <button
                    class="flex h-10 w-10 items-center justify-center rounded-lg border border-gray-300 bg-white text-gray-600 hover:bg-gray-100 disabled:cursor-wait disabled:opacity-50"
                    aria-label="Refresh indexed documents" :disabled="isLoading" @click="loadDocuments">
                    <LoaderCircle v-if="isLoading" class="h-4 w-4 animate-spin" aria-hidden="true" />
                    <RefreshCw v-else class="h-4 w-4" aria-hidden="true" />
                </button>
            </div>
        </div>

        <div class="flex-1 overflow-y-auto px-6 py-5">
            <div v-if="isLoading && !documents.length"
                class="flex items-center justify-center gap-2 py-12 text-sm text-gray-500">
                <LoaderCircle class="h-4 w-4 animate-spin" aria-hidden="true" />
                Loading indexed documents...
            </div>

            <div v-else-if="errorMessage" class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {{ errorMessage }}
            </div>

            <div v-else-if="!filteredDocuments.length" class="py-12 text-center text-sm text-gray-500">
                {{ searchQuery ? 'No documents match your search.' : 'No documents have been indexed yet.' }}
            </div>

            <ul v-else class="space-y-3">
                <li v-for="document in filteredDocuments" :key="document.id"
                    class="rounded-lg border border-gray-200 bg-white p-4">
                    <div class="flex items-start gap-3">
                        <FileText class="mt-0.5 h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" />
                        <div class="min-w-0">
                            <p class="mt-1 break-words text-xs text-gray-500">{{ document.filename }}</p>
                        </div>
                    </div>
                </li>
            </ul>
        </div>
    </aside>

    <div v-else
        class="fixed inset-y-0 right-0 z-50 flex h-full w-10 shrink-0 flex-col items-center bg-white py-2 shadow-lg lg:static lg:z-auto lg:shadow-none">
        <button type="button" @click="emit('open')"
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
            aria-label="Open indexed documents" title="Open indexed documents">
            <PanelRightOpen class="h-5 w-5" aria-hidden="true" />
        </button>
    </div>
</template>