<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { BookOpen, FileText, LoaderCircle, PanelRightClose, PanelRightOpen, RefreshCw, Search, Trash2, Upload } from '@lucide/vue';
import { useApiRequest, useApiStream, useHandleApiResponse } from '../composables/useApi';
import DialogBox from './DialogBox.vue';

interface IndexedDocument {
    id: number;
    document_id: string;
    filename: string;
}

interface IngestionStart {
    job_id: string;
    filename: string;
}

interface IngestionEvent {
    type: 'ingestion_progress' | 'ingestion_complete' | 'ingestion_error';
    percent?: number;
    message: string;
}

const props = defineProps<{ isOpen: boolean }>();
const emit = defineEmits<{
    (event: 'close'): void;
    (event: 'open'): void;
}>();

const documents = ref<IndexedDocument[]>([]);
const searchQuery = ref('');
const isLoading = ref(false);
const errorMessage = ref('');
const fileInput = ref<HTMLInputElement | null>(null);
const isIngesting = ref(false);
const ingestionProgress = ref(0);
const ingestionMessage = ref('');
const ingestionError = ref('');
const deletingDocumentId = ref<number | null>(null);
const documentPendingDeletion = ref<IndexedDocument | null>(null);
const deleteError = ref('');
const deleteDialogOpen = computed(() => documentPendingDeletion.value !== null);

const filteredDocuments = computed(() => {
    const query = searchQuery.value.trim().toLowerCase();
    if (!query) return documents.value;

    return documents.value.filter(document =>
        `${document.filename} ${document.document_id}`.toLowerCase().includes(query),
    );
});

const loadDocuments = async () => {
    isLoading.value = true;
    errorMessage.value = '';

    try {
        const response = await useApiRequest<IndexedDocument[]>(`/api/documents`);
        documents.value = useHandleApiResponse(response);
    } catch (error) {
        errorMessage.value = error instanceof Error
            ? error.message
            : 'Unable to load indexed documents.';
    } finally {
        isLoading.value = false;
    }
};

const openFilePicker = () => fileInput.value?.click();

const consumeIngestionEvents = async (response: Response) => {
    if (!response.ok || !response.body) {
        throw new Error('Unable to receive ingestion progress.');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let boundaryIndex = buffer.indexOf('\n\n');
        while (boundaryIndex !== -1) {
            const block = buffer.slice(0, boundaryIndex);
            buffer = buffer.slice(boundaryIndex + 2);
            const payload = block
                .split(/\r?\n/)
                .filter(line => line.startsWith('data:'))
                .map(line => line.slice(5).trimStart())
                .join('\n');

            if (payload) {
                const event = JSON.parse(payload) as IngestionEvent;
                ingestionMessage.value = event.message;
                if (event.type === 'ingestion_progress') {
                    ingestionProgress.value = event.percent ?? ingestionProgress.value;
                } else if (event.type === 'ingestion_error') {
                    throw new Error(event.message);
                } else if (event.type === 'ingestion_complete') {
                    ingestionProgress.value = 100;
                    await loadDocuments();
                }
            }
            boundaryIndex = buffer.indexOf('\n\n');
        }
    }
};

const uploadDocument = async (event: Event) => {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file || isIngesting.value) return;

    isIngesting.value = true;
    ingestionProgress.value = 0;
    ingestionMessage.value = 'Saving document...';
    ingestionError.value = '';

    try {
        const formData = new FormData();
        formData.append('file', file);
        const response = await useApiRequest<IngestionStart>('/api/documents/ingestions', {
            method: 'POST',
            body: formData,
        });
        const { job_id } = useHandleApiResponse(response);
        await consumeIngestionEvents(
            await useApiStream(`/api/documents/ingestions/${job_id}/events`),
        );
    } catch (error) {
        ingestionError.value = error instanceof Error ? error.message : 'Unable to ingest the document.';
    } finally {
        isIngesting.value = false;
    }
};

const requestDocumentDeletion = (document: IndexedDocument) => {
    if (deletingDocumentId.value !== null) return;
    documentPendingDeletion.value = document;
    deleteError.value = '';
};

const closeDeleteDialog = () => {
    if (deletingDocumentId.value !== null) return;
    documentPendingDeletion.value = null;
    deleteError.value = '';
};

const confirmDocumentDeletion = async () => {
    const document = documentPendingDeletion.value;
    if (!document) return;

    deletingDocumentId.value = document.id;
    deleteError.value = '';
    try {
        const response = await useApiRequest<{ id: number }>(`/api/documents/${document.id}`, {
            method: 'DELETE',
        });
        useHandleApiResponse(response);
        documents.value = documents.value.filter(item => item.id !== document.id);
        documentPendingDeletion.value = null;
    } catch (error) {
        deleteError.value = error instanceof Error ? error.message : 'Unable to delete the document.';
    } finally {
        deletingDocumentId.value = null;
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
            <input ref="fileInput" type="file" accept="application/pdf,.pdf" class="sr-only" @change="uploadDocument" />
            <button type="button"
                class="mb-3 flex w-full items-center justify-center gap-2 rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:cursor-wait disabled:opacity-60"
                :disabled="isIngesting" @click="openFilePicker">
                <LoaderCircle v-if="isIngesting" class="h-4 w-4 animate-spin" aria-hidden="true" />
                <Upload v-else class="h-4 w-4" aria-hidden="true" />
                {{ isIngesting ? 'Indexing document...' : 'Upload PDF' }}
            </button>
            <div v-if="isIngesting" class="mb-3" aria-live="polite">
                <div class="h-1.5 overflow-hidden rounded-full bg-gray-200">
                    <div class="h-full bg-gray-900 transition-all" :style="{ width: `${ingestionProgress}%` }" />
                </div>
                <p class="mt-1 text-xs text-gray-600">{{ ingestionMessage }}</p>
            </div>
            <p v-else-if="ingestionError" class="mb-3 text-xs text-red-700">{{ ingestionError }}</p>
            <div class="flex gap-2">
                <label class="relative flex-1">
                    <Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
                        aria-hidden="true" />
                    <span class="sr-only">Search indexed documents</span>
                    <input v-model="searchQuery" type="search" placeholder="Search documents"
                        class="w-full rounded-md border border-gray-200 bg-white py-2 pl-9 pr-3 text-sm outline-none placeholder:text-gray-400 focus:border-gray-400 focus:ring-1 focus:ring-gray-200" />
                </label>
                <button
                    class="flex h-10 w-10 items-center justify-center rounded-lg border border-gray-300 bg-white text-gray-600 hover:bg-gray-100 disabled:cursor-wait disabled:opacity-50"
                    aria-label="Refresh indexed documents" :disabled="isLoading" @click="loadDocuments">
                    <LoaderCircle v-if="isLoading" class="h-4 w-4 animate-spin" aria-hidden="true" />
                    <RefreshCw v-else class="h-4 w-4" aria-hidden="true" />
                </button>
            </div>
        </div>

        <div class="flex-1 overflow-y-auto px-6">
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
                        <FileText class="mt-0.5 h-5 w-5 shrink-0 text-gray-500" aria-hidden="true" />
                        <div class="min-w-0">
                            <p class="break-words text-xs text-gray-500">{{ document.filename }}</p>
                            <p class="mt-1 text-[10px] text-gray-400" :title="document.document_id">
                                {{ document.document_id }}
                            </p>
                            <div class="mt-2 flex justify-between gap-3">
                                <RouterLink :to="{ name: 'parsed-document', params: { id: document.id } }"
                                    class="inline-flex gap-1 text-xs font-medium text-gray-700 hover:text-gray-900 hover:underline">
                                    <BookOpen class="h-3.5 w-3.5" aria-hidden="true" />
                                    <span>Show</span>
                                </RouterLink>
                                <button type="button"
                                    class="inline-flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-900 disabled:cursor-wait disabled:opacity-60"
                                    :disabled="deletingDocumentId === document.id"
                                    :aria-label="`Delete ${document.filename}`"
                                    @click="requestDocumentDeletion(document)">

                                    <LoaderCircle v-if="deletingDocumentId === document.id"
                                        class="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                                    <div class="flex items-center gap-1" v-else>
                                        <span>Delete</span>
                                        <Trash2 class="h-3.5 w-3.5" aria-hidden="true" />
                                    </div>
                                </button>
                            </div>
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

    <DialogBox :open="deleteDialogOpen" title="Delete document" cancel-text="Cancel"
        :loading="deletingDocumentId !== null" max-width="sm" @close="closeDeleteDialog">
        <p class="text-sm text-gray-600">
            Delete <span class="font-medium text-gray-900">{{ documentPendingDeletion?.filename }}</span>?
        </p>
        <p v-if="deleteError" role="alert"
            class="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {{ deleteError }}
        </p>

        <template #footer>
            <button type="button" :disabled="deletingDocumentId !== null"
                class="h-9 rounded-md px-3 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50"
                @click="closeDeleteDialog">
                Cancel
            </button>
            <button type="button" :disabled="deletingDocumentId !== null"
                class="inline-flex h-9 items-center gap-2 rounded-md bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-700 disabled:cursor-wait disabled:opacity-50"
                @click="confirmDocumentDeletion">
                <LoaderCircle v-if="deletingDocumentId !== null" class="h-4 w-4 animate-spin" aria-hidden="true" />
                Delete document
            </button>
        </template>
    </DialogBox>
</template>
