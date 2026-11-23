<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { ArrowLeft, Download, FileText, FileType, LoaderCircle } from '@lucide/vue';
import { useRoute, useRouter } from 'vue-router';
import { useApiRequest, useHandleApiResponse } from '@/composables/useApi';
import { renderMarkdown } from '@/utils/markdown';

interface ParsedDocument {
  document_id: string;
  filename: string;
  markdown: string;
}

const route = useRoute();
const router = useRouter();
const document = ref<ParsedDocument | null>(null);
const errorMessage = ref('');
const isLoading = ref(true);
const activeView = ref<'original' | 'parsed'>('original');

const renderedMarkdown = computed(() => renderMarkdown(document.value?.markdown ?? ''));
const wordCount = computed(() =>
  (document.value?.markdown.match(/\S+/g) ?? []).length,
);
const readingMinutes = computed(() => Math.max(1, Math.ceil(wordCount.value / 220)));
const documentId = computed(() => Number(route.params.id));

const goBack = () => {
  if (window.history.length > 1) {
    router.back();
  } else {
    router.push({ name: 'home' });
  }
};

onMounted(async () => {
  if (!Number.isInteger(documentId.value) || documentId.value < 1) {
    errorMessage.value = 'Invalid document.';
    isLoading.value = false;
    return;
  }

  try {
    const response = await useApiRequest<ParsedDocument>(`/api/documents/${documentId.value}/parsed`);
    document.value = useHandleApiResponse(response);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to load parsed document.';
  } finally {
    isLoading.value = false;
  }
});
</script>

<template>
  <div class="flex h-dvh min-h-0 flex-col overflow-hidden bg-white text-gray-900">
    <header class="flex h-16 shrink-0 items-center gap-4 border-b border-gray-200 px-5 sm:px-8">
      <button type="button" aria-label="Back to chat" title="Back to chat"
        class="flex h-9 w-9 items-center justify-center rounded-lg text-gray-500 transition hover:bg-gray-100 hover:text-gray-900"
        @click="goBack">
        <ArrowLeft :size="19" />
      </button>

      <h1 class="min-w-0 truncate text-lg font-semibold tracking-tight">
        {{ document?.filename ?? 'Document' }}
      </h1>
    </header>

    <main class="flex min-h-0 flex-1 flex-col overflow-hidden px-5 py-4 sm:px-8 sm:py-5">
      <section
        class="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div class="flex shrink-0 items-center justify-between gap-3 border-b border-gray-200 px-3 py-2 sm:px-4">
          <div class="flex rounded-md bg-gray-100 p-0.5" role="tablist" aria-label="Document view">
            <button type="button" role="tab" :aria-selected="activeView === 'original'"
              class="inline-flex h-8 items-center gap-1.5 rounded px-2.5 text-sm font-medium transition-colors"
              :class="activeView === 'original' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-900'"
              @click="activeView = 'original'">
              <FileType :size="15" aria-hidden="true" />
              Original PDF
            </button>
            <button type="button" role="tab" :aria-selected="activeView === 'parsed'"
              class="inline-flex h-8 items-center gap-1.5 rounded px-2.5 text-sm font-medium transition-colors"
              :class="activeView === 'parsed' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-900'"
              @click="activeView = 'parsed'">
              <FileText :size="15" aria-hidden="true" />
              Parsed content
            </button>
          </div>

          <div class="flex items-center gap-3">
            <p v-if="document" class="hidden text-xs text-gray-400 sm:block">
              {{ wordCount.toLocaleString() }} words · {{ readingMinutes }} min read
            </p>
            <a :href="`/api/documents/${documentId}/file`" target="_blank" rel="noopener" title="Download original PDF"
              aria-label="Download original PDF"
              class="flex h-8 w-8 items-center justify-center rounded-md text-gray-500 transition hover:bg-gray-100 hover:text-gray-900">
              <Download :size="16" />
            </a>
          </div>
        </div>

        <div class="relative min-h-0 flex-1">
          <div class="absolute inset-0 flex min-h-0"
            :class="activeView === 'original' ? 'z-10' : 'pointer-events-none opacity-0'"
            :aria-hidden="activeView !== 'original'" :inert="activeView !== 'original'">
            <iframe :src="`/api/documents/${documentId}/file`" :title="`Original PDF: ${document?.filename ?? ''}`"
              class="min-h-0 w-full flex-1 rounded bg-white" />
          </div>
          <div class="absolute inset-0 flex min-h-0 flex-col"
            :class="activeView === 'parsed' ? 'z-10' : 'pointer-events-none opacity-0'"
            :aria-hidden="activeView !== 'parsed'" :inert="activeView !== 'parsed'">
            <div v-if="isLoading"
              class="flex min-h-0 flex-1 items-center justify-center gap-2 px-5 py-16 text-sm text-gray-500">
              <LoaderCircle class="h-4 w-4 animate-spin" aria-hidden="true" />
              Loading parsed text...
            </div>
            <div v-else-if="errorMessage"
              class="m-5 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 sm:m-7">
              {{ errorMessage }}
            </div>
            <div v-else class="min-h-0 flex-1 overflow-y-auto bg-gray-50 px-5 py-7 sm:px-8 sm:py-9">
              <article
                class="prose prose-gray mx-auto max-w-3xl rounded-lg bg-white px-5 py-7 ring-1 ring-gray-200 prose-headings:scroll-mt-6 prose-headings:font-semibold prose-headings:tracking-tight prose-a:text-gray-900 prose-img:rounded-lg sm:px-10 sm:py-9"
                v-html="renderedMarkdown" />
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>
