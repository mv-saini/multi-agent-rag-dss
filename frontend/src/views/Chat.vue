<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue';
import MessageItem from '@/components/MessageItem.vue';
import SideDrawer from '@/components/SideDrawer.vue';
import MapOverlay from '@/components/MapOverlay.vue';
import ContextMenu from '@/components/ContextMenu.vue';
import DialogBox from '@/components/DialogBox.vue';
import ProfileNodeEditor from '@/components/ProfileNodeEditor.vue';
import DocumentList from '@/components/DocumentList.vue';
import ThreadSidebar from '@/components/ThreadSidebar.vue';
import ScenarioEditor from '@/components/ScenarioEditor.vue';
import type { ScenarioRequest, ScenarioSelection } from '@/types/app';
import { LoaderCircle, Map as MapIcon, Pencil, Send, Square, X } from '@lucide/vue';
import { useApiRequest, useApiStream, useHandleApiResponse } from '@/composables/useApi.ts';
import { useRouter } from 'vue-router';
import { useEvidence } from '@/composables/useEvidence';
import type { ChatThread, ContextMenuState, DisplayPlan, InboundCommand, Message, OutboundCommand, PendingInteraction, ThreadState } from '@/types/app.ts';

let activeRequestController: AbortController | null = null;
let threadLoadController: AbortController | null = null;
const router = useRouter();

const connectionStatus = ref<'idle' | 'streaming' | 'error'>('idle');
const isLoading = ref(false);
const isLoadingMessages = ref(false);
const userQuery = ref('');
const userQueryInput = ref<HTMLTextAreaElement | null>(null);
const messages = ref<Message[]>([]);
const messagesContainer = ref<HTMLDivElement | null>(null);
const chatAutoScrollEnabled = ref(true);
const reasoningHeader = ref<string>("Reasoning...");

const savedThreads = ref<ChatThread[]>([]);
const threadId = ref<string | null>(localStorage.getItem('vue_thread'));
const contextMenu = ref<ContextMenuState>({ open: false, x: 0, y: 0, thread: null });
const threadDialogAction = ref<'rename' | 'delete' | null>(null);
const threadPendingAction = ref<ChatThread | null>(null);
const threadTitleDraft = ref('');
const threadActionError = ref('');
const threadActionLoading = ref(false);
const threadDialogOpen = computed(
  () => threadDialogAction.value !== null && threadPendingAction.value !== null,
);
const threadDialogTitle = computed(
  () => threadDialogAction.value === 'rename' ? 'Rename conversation' : 'Delete conversation',
);

const isPausedWaitingForFeedback = ref(false);
const pendingCheckpointId = ref<string | null>(null);
const scenarioRequest = ref<ScenarioRequest | null>(null);
const showScenarioEditor = ref(false);
const isPlanApprovalPending = computed(() =>
  isPausedWaitingForFeedback.value && messages.value[messages.value.length - 1]?.interaction?.kind === 'plan_approval',
);

const {
  bundles: evidenceBundles, mapLayers, loading: loadingEvidence, activeMapLayerIds, error: evidenceError,
  reset: resetEvidence, load: loadEvidence, loadAll: loadAllEvidence, retry: retryEvidence,
} = useEvidence(threadId);
const isMapOverlayOpen = ref(false);

const isDrawerOpen = ref(false);
const drawerType = ref<'plan' | 'context' | null>(null);
const drawerPlanData = ref<DisplayPlan | null>(null);
const drawerContextData = ref<Record<string, string> | null>(null);

const DEFAULT_PROFILE = {
  "role": "emergency_coordinator",
  "expertise_level": "operational",
  "language_preference": "English",
  "preferred_output": { "detail_level": "high", "include_sources": true }
};

const loadProfile = () => {
  const stored = localStorage.getItem('vue_user_profile');
  if (stored) {
    try {
      return JSON.parse(stored);
    } catch (e) {
      console.error('Failed to parse stored profile, falling back to default', e);
      return DEFAULT_PROFILE;
    }
  }
  return DEFAULT_PROFILE;
};

const usrPfp = ref(loadProfile());

// const usrPfp = ref({
//   "role": "researcher",
//   "expertise_level": "expert",
//   "language_preference": "English",
//   "preferred_output": { "detail_level": "very_high", "include_sources": true },
// })

// const usrPfp = ref({
//   "role": "urban_planner",
//   "expertise_level": "technical",
//   "language_preference": "English",
//   "preferred_output": { "detail_level": "high", "include_sources": true },
// })

// const usrPfp = ref({
//   "role": "municipal_decision_maker",
//   "expertise_level": "policy_maker",
//   "language_preference": "Italian",
//   "preferred_output": { "detail_level": "medium", "include_sources": true },
// })

// const usrPfp = ref({
//   "role": "infrastructure_operator",
//   "expertise_level": "technical",
//   "language_preference": "English",
//   "preferred_output": { "detail_level": "high", "include_sources": true },
// })

// const usrPfp = ref({
//   "role": "resident",
//   "expertise_level": "non_technical",
//   "language_preference": "Italian",
//   "preferred_output": { "detail_level": "concise", "include_sources": false },
// })

const isProfileModalOpen = ref(false);
const isThreadListOpen = ref(localStorage.getItem('vue_thread_list_open') !== 'false');
const isDocumentListOpen = ref(localStorage.getItem('vue_document_list_open') !== 'false');

watch(isThreadListOpen, (isOpen) => {
  localStorage.setItem('vue_thread_list_open', String(isOpen));
});

watch(isDocumentListOpen, (isOpen) => {
  localStorage.setItem('vue_document_list_open', String(isOpen));
});
const profileDraft = ref<Record<string, unknown>>({});
const profileError = ref('');

const cloneProfile = (profile: Record<string, unknown>) => JSON.parse(JSON.stringify(profile)) as Record<string, unknown>;

const openProfile = () => {
  profileDraft.value = cloneProfile(usrPfp.value);
  profileError.value = '';
  isProfileModalOpen.value = true;
};

const openUsers = () => {
  router.push({ name: 'users' });
};

const saveProfile = () => {
  try {
    usrPfp.value = cloneProfile(profileDraft.value);
    localStorage.setItem('vue_user_profile', JSON.stringify(usrPfp.value));
    isProfileModalOpen.value = false;
  } catch (e: any) {
    profileError.value = e.message || 'Unable to save this profile.';
  }
};

const resizeQueryInput = () => {
  const input = userQueryInput.value;
  if (!input) return;
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
};

const scrollToBottom = async () => {
  if (!chatAutoScrollEnabled.value || !messagesContainer.value) return;
  await nextTick();
  messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
};

const handleScroll = () => {
  if (!messagesContainer.value) return;
  const { scrollHeight, scrollTop, clientHeight } = messagesContainer.value;
  chatAutoScrollEnabled.value = (scrollHeight - scrollTop - clientHeight) < 10;
};

const openDrawer = (type: 'plan' | 'context', data: any) => {
  drawerType.value = type;
  if (type === 'plan') drawerPlanData.value = data;
  if (type === 'context') drawerContextData.value = data;
  isDrawerOpen.value = true;
};

const persistActiveThread = () => {
  if (threadId.value) localStorage.setItem('vue_thread', threadId.value);
};

const createNewThread = () => {
  stopQuery();
  threadId.value = null;
  localStorage.removeItem('vue_thread');
  messages.value = [];
  resetEvidence();
  clearPendingInteraction();
  connectionStatus.value = 'idle';
};

const selectThread = async (id: string) => {
  if (threadId.value === id && messages.value.length) return;
  stopQuery();
  threadId.value = id;
  persistActiveThread();
  messages.value = [];
  resetEvidence();
  connectionStatus.value = 'idle';
  await loadThreadState(id);
};

const openContextMenu = (e: MouseEvent, thread: ChatThread) => {
  e.preventDefault();
  contextMenu.value = { open: true, x: e.clientX, y: e.clientY, thread };
};
const closeContextMenu = () => { contextMenu.value.open = false; };

const renameContextThread = () => {
  const target = contextMenu.value.thread;
  if (!target) return;

  threadPendingAction.value = target;
  threadTitleDraft.value = target.title;
  threadActionError.value = '';
  threadDialogAction.value = 'rename';
  closeContextMenu();
};

const deleteContextThread = () => {
  const target = contextMenu.value.thread;
  if (!target) return;

  threadPendingAction.value = target;
  threadActionError.value = '';
  threadDialogAction.value = 'delete';
  closeContextMenu();
};

const closeThreadDialog = () => {
  if (threadActionLoading.value) return;
  threadDialogAction.value = null;
  threadPendingAction.value = null;
  threadTitleDraft.value = '';
  threadActionError.value = '';
};

const confirmThreadAction = async () => {
  const target = threadPendingAction.value;
  const action = threadDialogAction.value;
  if (!target || !action || threadActionLoading.value) return;

  const nextTitle = threadTitleDraft.value.trim();
  if (action === 'rename' && !nextTitle) {
    threadActionError.value = 'Conversation title cannot be empty.';
    return;
  }

  if (action === 'rename' && nextTitle === target.title) {
    closeThreadDialog();
    return;
  }

  threadActionLoading.value = true;
  threadActionError.value = '';
  let succeeded = false;
  try {
    if (action === 'rename') {
      const response = await useApiRequest<ChatThread>(
        `/api/threads/${encodeURIComponent(target.conversationid)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: nextTitle }),
        },
      );
      const updatedThread = useHandleApiResponse(response);
      const index = savedThreads.value.findIndex(
        item => item.conversationid === target.conversationid,
      );
      if (index !== -1) savedThreads.value[index] = updatedThread;
    } else {
      const response = await useApiRequest<{ conversationid: string }>(
        `/api/threads/${encodeURIComponent(target.conversationid)}`,
        { method: 'DELETE' },
      );
      useHandleApiResponse(response);

      const deletingActiveThread = threadId.value === target.conversationid;
      savedThreads.value = savedThreads.value.filter(
        item => item.conversationid !== target.conversationid,
      );
      if (deletingActiveThread) createNewThread();
    }
    succeeded = true;
  } catch (error) {
    threadActionError.value = error instanceof Error
      ? error.message
      : `Unable to ${action} the conversation.`;
  } finally {
    threadActionLoading.value = false;
  }

  if (succeeded) closeThreadDialog();
};

const ensureAssistantPlaceholder = () => {
  if (messages.value[messages.value.length - 1]?.role !== 'assistant') {
    messages.value.push({ role: 'assistant', content: '', reasoning: '', isReasoningExpanded: false });
  }
};
const currentAssistantMessage = () => {
  ensureAssistantPlaceholder();
  return messages.value[messages.value.length - 1]!;
};

const updateUserMessageId = (messageId: string) => {
  const index = [...messages.value].reverse().findIndex(
    message => message.role === 'user' && !message.id,
  );
  if (index === -1) return;
  messages.value[messages.value.length - 1 - index]!.id = messageId;
};

const updateMessage = (message: Message) => {
  if (!message.id) return;
  let index = messages.value.findIndex(existing => existing.id === message.id);
  if (index === -1 && message.role === 'assistant') {
    for (let candidate = messages.value.length - 1; candidate >= 0; candidate -= 1) {
      const existing = messages.value[candidate];
      if (existing?.role === 'assistant' && !existing.id) {
        index = candidate;
        break;
      }
    }
  }
  if (index === -1) {
    messages.value.push(message);
    return;
  }
  messages.value[index] = { ...messages.value[index], ...message };
};

const clearPendingInteraction = () => {
  isPausedWaitingForFeedback.value = false;
  pendingCheckpointId.value = null;
  scenarioRequest.value = null;
  showScenarioEditor.value = false;
};

const appendInteractionMessage = (interaction: PendingInteraction) => {
  messages.value.push({
    role: 'assistant',
    content: interaction.message || '',
    reasoning: '',
    isReasoningExpanded: false,
    interaction,
  });
};

const restorePendingInteraction = (interaction?: PendingInteraction | null, checkpointId?: string | null) => {
  clearPendingInteraction();
  if (!interaction) return;
  isPausedWaitingForFeedback.value = true;
  pendingCheckpointId.value = checkpointId || null;
  if (interaction.kind === 'clarification' && interaction.scenario_request) {
    scenarioRequest.value = interaction.scenario_request;
  }
  appendInteractionMessage(interaction);
};

const loadThreadState = async (id: string) => {
  threadLoadController?.abort();
  const controller = new AbortController();
  threadLoadController = controller;
  isLoadingMessages.value = true;
  try {
    const response = await useApiRequest<ThreadState>(`/api/history/${encodeURIComponent(id)}`, {
      signal: controller.signal,
    });
    const data = useHandleApiResponse(response);
    if (controller.signal.aborted || threadId.value !== id) return;
    messages.value = data.messages || [];
    isLoadingMessages.value = false;
    loadAllEvidence(data.evidence_bundle_ids || []);
    if (controller.signal.aborted || threadId.value !== id) return;
    restorePendingInteraction(data.pending_interaction, data.checkpoint_id);
    isLoading.value = Boolean(data.is_running);
    connectionStatus.value = data.is_errored
      ? 'error'
      : data.is_running
        ? 'streaming'
        : 'idle';
    await scrollToBottom();

    if (!controller.signal.aborted && data.is_running && threadId.value === id) {
      void subscribeToThread(id);
    }
  } catch (error) {
    if (!controller.signal.aborted && threadId.value === id) {
      connectionStatus.value = 'error';
    }
  } finally {
    if (threadLoadController === controller) {
      threadLoadController = null;
      isLoadingMessages.value = false;
    }
  }
};

const applyStreamEvent = async (data: InboundCommand) => {
  switch (data.type) {
    case 'stream_started':
      isLoading.value = true;
      connectionStatus.value = 'streaming';
      return;
    case 'message_started':
      updateUserMessageId(data.message_id);
      return;
    case 'message_update':
      updateMessage(data.message);
      if (data.message.additional_kwargs?.evidence_bundle_id) {
        await loadEvidence(data.message.additional_kwargs.evidence_bundle_id);
      }
      return;
    case 'approval_required':
      restorePendingInteraction(data.interaction, data.checkpoint_id);
      isLoading.value = false;
      connectionStatus.value = 'idle';
      scrollToBottom();
      return;
    case 'stream_complete':
      isLoading.value = false;
      connectionStatus.value = 'idle';
      if (data.status === 'completed') clearPendingInteraction();
      return;
    case 'stream_error':
      currentAssistantMessage().content = data.message;
      currentAssistantMessage().reasoning = '';
      isLoading.value = false;
      connectionStatus.value = 'error';
      scrollToBottom();
      return;
    case 'token':
      currentAssistantMessage().content += data.content;
      scrollToBottom();
      return;
    case 'reasoning':
      currentAssistantMessage().reasoning += data.content;
      return;
    case 'tool_start':
      currentAssistantMessage().reasoning += `\n\n**${data.name}...**\n`;
      return;
    case 'retriever_start':
      currentAssistantMessage().reasoning +=
        `\n\n**Retrieving documents**${data.query ? ` for query: ${data.query}` : ''
        }...\n`;
      return;
    case 'evidence_available':
      await loadEvidence(data.evidence_bundle_id);
      return;
    case 'custom_event':
      handleCustomEvent(data);
      return;
  }
};

const handleCustomEvent = (data: InboundCommand) => {
  if (data.type !== 'custom_event') return;
  if (data.name === 'reasoning_header') {
    ensureAssistantPlaceholder();
    reasoningHeader.value = data.data;
    scrollToBottom();
  } else if (data.name === 'fusion_start') {
    currentAssistantMessage().reasoning +=
      `\n\n**Fusing documents...**\n`;
  } else if (data.name === 'rerank_start') {
    currentAssistantMessage().reasoning +=
      `\n\n**Reranking documents...**\n\n`;
  }
}

const handleNewThread = (thread: ChatThread) => {
  threadId.value = thread.conversationid;
  persistActiveThread();
  savedThreads.value = [
    thread,
    ...savedThreads.value.filter(
      existing => existing.conversationid !== thread.conversationid,
    ),
  ];
};

const consumeEventStream = async (
  response: Response,
  initialThreadId: string | null,
): Promise<string | null> => {
  if (!response.body) throw new Error('Stream response had no body');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let expectedThreadId = initialThreadId;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundaryIndex = buffer.indexOf('\n\n');
    while (boundaryIndex !== -1) {
      const block = buffer.slice(0, boundaryIndex);
      buffer = buffer.slice(boundaryIndex + 2);

      const dataLines = block.split(/\r?\n/)
        .filter(line => line.startsWith('data:'))
        .map(line => line.slice(5).trimStart());

      if (dataLines.length) {
        const data = JSON.parse(dataLines.join('\n')) as InboundCommand;
        if (data.type === 'new_thread') {
          handleNewThread(data.thread);
          expectedThreadId = data.thread.conversationid;
        } else if (threadId.value === expectedThreadId) {
          await applyStreamEvent(data);
        }
      }

      boundaryIndex = buffer.indexOf('\n\n');
    }
  }

  return expectedThreadId;
};

const subscribeToThread = async (id: string) => {
  const controller = new AbortController();
  activeRequestController?.abort();
  activeRequestController = controller;

  try {
    const response = await useApiStream(
      `/api/threads/${encodeURIComponent(id)}/events`,
      { signal: controller.signal },
    );

    if (response.status === 204) return;
    if (!response.ok) throw new Error(`Stream request failed (${response.status})`);

    await consumeEventStream(response, id);
  } catch (error: any) {
    if (error.name !== 'AbortError' && threadId.value === id) {
      connectionStatus.value = 'error';
    }
  } finally {
    if (activeRequestController === controller) {
      activeRequestController = null;
      isLoading.value = false;
      if (connectionStatus.value === 'streaming') connectionStatus.value = 'idle';
    }
  }
};

const streamCommand = async (command: OutboundCommand) => {
  activeRequestController?.abort();
  const controller = new AbortController();
  activeRequestController = controller;
  isLoading.value = true;
  connectionStatus.value = 'streaming';
  let expectedThreadId = threadId.value;

  try {
    const endpoint = expectedThreadId
      ? `/api/threads/${encodeURIComponent(expectedThreadId)}/commands`
      : '/api/threads/commands';
    const response = await useApiStream(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(command),
      signal: controller.signal,
    });

    if (!response.ok) {
      let message = `Stream request failed (${response.status})`;
      try {
        const errorResponse = await response.json() as { error?: string };
        if (errorResponse.error) message = errorResponse.error;
      } catch {
        // Keep the status-based error when the response is not JSON.
      }
      throw new Error(message);
    }

    expectedThreadId = await consumeEventStream(response, expectedThreadId);
  } catch (error: any) {
    if (error.name === 'AbortError') return;
    if (threadId.value === expectedThreadId) {
      currentAssistantMessage().content = error.message || 'Unable to start the conversation.';
      connectionStatus.value = 'error';
    }
  } finally {
    if (activeRequestController === controller) {
      activeRequestController = null;
      isLoading.value = false;
      if (connectionStatus.value === 'streaming') connectionStatus.value = 'idle';
    }
  }
};

const getThreads = async () => {
  try {
    const response = await useApiRequest<ChatThread[]>(`/api/threads`);
    const data = useHandleApiResponse(response);
    savedThreads.value = data;
  } catch (error) {
    console.error('Failed to fetch threads:', error);
  }
};

const startQuery = () => {
  const query = userQuery.value.trim();
  if (!query || isLoading.value) return;

  const isResuming = isPausedWaitingForFeedback.value;

  messages.value.push({ role: 'user', content: query, reasoning: '', isReasoningExpanded: false });
  userQuery.value = '';
  nextTick(resizeQueryInput);

  if (!isResuming) ensureAssistantPlaceholder();
  scrollToBottom();

  if (isPausedWaitingForFeedback.value) {
    const cpId = pendingCheckpointId.value;
    clearPendingInteraction();
    streamCommand({ action: 'resume', response: query, checkpoint_id: cpId });
  } else {
    streamCommand({ action: 'query', query, user_profile: usrPfp.value });
  }
};

const approvePlan = () => {
  if (!isPlanApprovalPending.value || isLoading.value) return;
  const cpId = pendingCheckpointId.value;
  messages.value.push({ role: 'user', content: 'Plan approved.', reasoning: '', isReasoningExpanded: false });
  clearPendingInteraction();
  scrollToBottom();
  void streamCommand({ action: 'resume', response: 'yes', checkpoint_id: cpId });
};

const submitScenario = (selection: ScenarioSelection) => {
  const cpId = pendingCheckpointId.value;
  const scenario = selection.scenario;
  const response = `Use fault ${scenario.fault_id}, Mw ${scenario.magnitude}, ${scenario.resolution_m} m grid, ${scenario.intensity_measure}${scenario.period_s ? ` at ${scenario.period_s} s` : ''}, area: ${scenario.area_mode}.`;
  messages.value.push({ role: 'user', content: response, reasoning: '', isReasoningExpanded: false });
  clearPendingInteraction();
  void streamCommand({ action: 'resume', response, checkpoint_id: cpId, scenario_selection: selection });
};

const stopQuery = () => {
  threadLoadController?.abort();
  threadLoadController = null;
  isLoadingMessages.value = false;
  activeRequestController?.abort();
  activeRequestController = null;
  isLoading.value = false;
  connectionStatus.value = 'idle';
};

onMounted(async () => {
  await getThreads();
  if (threadId.value) await loadThreadState(threadId.value);
});

onBeforeUnmount(stopQuery);
</script>

<template>
  <div class="flex flex-col gap-1 h-screen w-full">
    <div class="relative flex h-[100vh] w-full min-h-0 flex-row">
      <ThreadSidebar :is-open="isThreadListOpen" :threads="savedThreads" :active-thread-id="threadId"
        :connection-status="connectionStatus" @close="isThreadListOpen = false" @open="isThreadListOpen = true"
        @create-new="createNewThread" @open-profile="openProfile" @select="closeContextMenu(); selectThread($event)"
        @context-menu="openContextMenu" @open-users="openUsers" />

      <button v-if="isThreadListOpen || isDocumentListOpen" type="button"
        class="fixed inset-0 z-40 bg-gray-900/30 lg:hidden" aria-label="Close side panels"
        @click="isThreadListOpen = false; isDocumentListOpen = false"></button>

      <!-- Chat -->
      <div
        class="mx-10 flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-x border-gray-200 bg-white lg:mx-auto">

        <!-- Messages -->
        <div class="flex-1 overflow-y-auto flex pt-4 flex-col gap-4" ref="messagesContainer" @scroll="handleScroll">
          <div v-if="isLoadingMessages" role="status"
            class="flex flex-1 items-center justify-center gap-2 text-sm text-gray-500">
            <LoaderCircle class="h-5 w-5 animate-spin" aria-hidden="true" />
          </div>
          <MessageItem v-for="(msg, index) in messages" :key="index" :msg="msg"
            :evidence="evidenceBundles[msg.additional_kwargs?.evidence_bundle_id || '']"
            :loadingEvidence="loadingEvidence"
            :isGenerating="isLoading && index === messages.length - 1 && !isPausedWaitingForFeedback"
            :can-edit-scenario="Boolean(scenarioRequest && isPausedWaitingForFeedback && index === messages.length - 1)"
            :can-approve-plan="isPlanApprovalPending && !isLoading && index === messages.length - 1"
            :reasoningHeader="reasoningHeader" @update:reasoningExpanded="msg.isReasoningExpanded = $event"
            @open-scenario="showScenarioEditor = true" @open-plan="openDrawer('plan', $event)"
            @approve-plan="approvePlan" @open-context="openDrawer('context', $event)" />
        </div>

        <div v-if="evidenceError" role="alert" class="px-4 py-2 text-sm text-red-700">
          Context and maps could not be loaded: {{ evidenceError }}
          <button class="ml-2 underline" @click="retryEvidence">Retry</button>
        </div>

        <!-- Inputs -->
        <div class="flex p-4 border-t border-gray-200 gap-2 bg-white items-end">
          <div v-if="loadingEvidence"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-gray-300 text-gray-600"
            role="status" aria-label="Loading map" title="Loading map">
            <LoaderCircle class="h-4 w-4 animate-spin" aria-hidden="true" />
          </div>
          <button v-if="!loadingEvidence && mapLayers.length" type="button" @click="isMapOverlayOpen = true"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-gray-300 text-gray-600 transition-colors hover:border-blue-500 hover:bg-blue-50 hover:text-blue-600"
            aria-label="Open map" title="Open map">
            <MapIcon class="h-4 w-4" aria-hidden="true" />
          </button>

          <textarea ref="userQueryInput" v-model="userQuery"
            :placeholder="isPlanApprovalPending ? 'Reject the plan or describe requested changes...' : 'Ask a question...'"
            :disabled="isLoading"
            class="min-h-11 max-h-45 flex-1 resize-none overflow-y-auto rounded-lg border border-gray-300 px-4 py-2.5 leading-6 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed"
            @input="resizeQueryInput" @keydown.enter.exact.prevent="startQuery" rows="1"></textarea>

          <button v-if="isLoading" @click="stopQuery"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-red-600 p-3.5 text-white transition-colors hover:bg-red-700">
            <Square class="block h-4 w-4 shrink-0 fill-current" aria-hidden="true" />
          </button>

          <button v-else @click="startQuery" :disabled="!userQuery.trim()"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-600 p-3.5 text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed">
            <Send class="block h-4 w-4 shrink-0" aria-hidden="true" />
          </button>
        </div>
      </div>

      <DocumentList :is-open="isDocumentListOpen" @close="isDocumentListOpen = false"
        @open="isDocumentListOpen = true" />
    </div>

    <!-- Profile Modal -->
    <div v-if="isProfileModalOpen" class="fixed inset-0 z-50 flex h-screen w-screen bg-white">
      <div class="flex h-full w-full flex-col overflow-hidden">
        <div class="px-6 py-5 border-b border-gray-200 flex justify-between items-start bg-gray-50">
          <div>
            <p class="text-xs font-semibold uppercase tracking-widest text-blue-600">Personal settings</p>
            <h3 class="font-semibold text-gray-900 text-xl mt-1">User Profile</h3>
          </div>
          <button @click="isProfileModalOpen = false" aria-label="Close profile editor"
            class="h-9 w-9 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-white flex items-center justify-center">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div class="p-6 overflow-y-auto flex-1">

          <ProfileNodeEditor v-model="profileDraft" label="Profile" />

          <p v-if="profileError" class="text-red-600 text-sm font-medium mt-3">
            {{ profileError }}
          </p>
        </div>

        <div class="px-6 py-4 border-t border-gray-200 flex justify-end gap-3 bg-gray-50">
          <button @click="isProfileModalOpen = false"
            class="px-5 py-2.5 rounded-xl text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 font-medium transition-colors">
            Cancel
          </button>
          <button @click="saveProfile"
            class="px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium transition-colors">
            <Pencil class="mr-2 inline-block h-4 w-4" aria-hidden="true" />
            Save Profile
          </button>
        </div>
      </div>
    </div>

    <!-- Overlays -->
    <ScenarioEditor v-if="scenarioRequest && showScenarioEditor" :request="scenarioRequest" @select="submitScenario"
      @close="showScenarioEditor = false" />
    <MapOverlay :show="isMapOverlayOpen" :layers="mapLayers" :activeLayerIds="activeMapLayerIds"
      @update:activeLayers="activeMapLayerIds = $event" @close="isMapOverlayOpen = false" />

    <SideDrawer :isOpen="isDrawerOpen" :type="drawerType" :planData="drawerPlanData" :contextData="drawerContextData"
      @close="isDrawerOpen = false" />

    <ContextMenu :open="contextMenu.open" :x="contextMenu.x" :y="contextMenu.y"
      :thread-title="contextMenu.thread?.title" @close="closeContextMenu" @rename="renameContextThread"
      @delete="deleteContextThread" />

    <DialogBox :open="threadDialogOpen" :title="threadDialogTitle" :loading="threadActionLoading" max-width="sm"
      @close="closeThreadDialog">
      <form id="thread-action-form" @submit.prevent="confirmThreadAction">
        <div v-if="threadDialogAction === 'rename'">
          <label for="thread-title" class="mb-1.5 block text-sm text-gray-600">
            Conversation title
          </label>
          <input id="thread-title" v-model="threadTitleDraft" required maxlength="100" :disabled="threadActionLoading"
            autofocus
            class="h-10 w-full rounded-md border border-gray-200 px-3 text-sm outline-none focus:border-gray-400 disabled:bg-gray-50" />
        </div>

        <p v-else class="text-sm text-gray-600">
          Permanently delete
          <span class="font-medium text-gray-900">{{ threadPendingAction?.title }}</span>?
          This action cannot be undone.
        </p>

        <p v-if="threadActionError" role="alert"
          class="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {{ threadActionError }}
        </p>
      </form>

      <template #footer>
        <button type="button" :disabled="threadActionLoading"
          class="h-9 rounded-md px-3 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50"
          @click="closeThreadDialog">
          Cancel
        </button>
        <button type="submit" form="thread-action-form" :disabled="threadActionLoading"
          class="h-9 rounded-md bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-700 disabled:cursor-wait disabled:opacity-50">
          {{ threadActionLoading ? 'Please wait...' : threadDialogAction === 'rename' ? 'Rename' : 'Delete' }}
        </button>
      </template>
    </DialogBox>
  </div>
</template>
