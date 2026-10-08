<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue';
import MessageItem from './components/MessageItem.vue';
import SideDrawer from './components/SideDrawer.vue';
import MapOverlay from './components/MapOverlay.vue';
import ContextMenu from "./components/ContextMenu.vue";
import ProfileNodeEditor from './components/ProfileNodeEditor.vue';
import DocumentList from './components/DocumentList.vue';
import ThreadSidebar from './components/ThreadSidebar.vue';
import { Map as MapIcon, Pencil, Send, Square, X } from '@lucide/vue';
import type { ChatThread, ContextMenuState, DisplayPlan, HazardMapLayer, InboundCommand, Message, OutboundCommand, PendingInteraction } from './types/app.ts';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
let activeRequestController: AbortController | null = null;

const connectionStatus = ref<'idle' | 'streaming' | 'error'>('idle');
const isLoading = ref(false);
const userQuery = ref('');
const userQueryInput = ref<HTMLTextAreaElement | null>(null);
const messages = ref<Message[]>([]);
const messagesContainer = ref<HTMLDivElement | null>(null);
const chatAutoScrollEnabled = ref(true);
const reasoningHeader = ref<string>("Reasoning...");

const savedThreads = ref<ChatThread[]>([]);
const threadId = ref(localStorage.getItem('vue_thread') || ('vue_thread_' + Math.random().toString(36).substring(7)));
const contextMenu = ref<ContextMenuState>({ open: false, x: 0, y: 0, thread: null });

const isPausedWaitingForFeedback = ref(false);
const pendingCheckpointId = ref<string | null>(null);

const mapLayers = ref<HazardMapLayer[]>([]);
const activeMapLayerIds = ref<string[]>([]);
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
const isThreadListOpen = ref(true);
const isDocumentListOpen = ref(false);
const profileDraft = ref<Record<string, unknown>>({});
const profileError = ref('');

const cloneProfile = (profile: Record<string, unknown>) => JSON.parse(JSON.stringify(profile)) as Record<string, unknown>;

const openProfile = () => {
  profileDraft.value = cloneProfile(usrPfp.value);
  profileError.value = '';
  isProfileModalOpen.value = true;
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

const persistThreads = () => localStorage.setItem('chat_threads', JSON.stringify(savedThreads.value));
const persistActiveThread = () => localStorage.setItem('vue_thread', threadId.value);

const createNewThread = () => {
  stopQuery();
  threadId.value = 'vue_thread_' + Math.random().toString(36).substring(7);
  persistActiveThread();
  messages.value = [];
  mapLayers.value = [];
  activeMapLayerIds.value = [];
  clearPendingInteraction();
  connectionStatus.value = 'idle';
};

const selectThread = async (id: string) => {
  if (threadId.value === id && messages.value.length) return;
  stopQuery();
  threadId.value = id;
  persistActiveThread();
  messages.value = [];
  mapLayers.value = [];
  activeMapLayerIds.value = [];
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

  const nextTitle = window.prompt(
    'Rename conversation',
    target.title,
  )?.trim();

  if (!nextTitle || nextTitle === target.title) {
    closeContextMenu();
    return;
  }

  const thread = savedThreads.value.find(
    item => item.id === target.id,
  );

  if (thread) {
    thread.title = nextTitle;
    persistThreads();
  }

  closeContextMenu();
};

const deleteContextThread = async () => {
  const target = contextMenu.value.thread;
  if (!target) return;

  const confirmed = window.confirm(
    `Delete “${target.title}” from this device?`,
  );

  if (!confirmed) {
    closeContextMenu();
    return;
  }

  const deletingActiveThread = threadId.value === target.id;
  savedThreads.value = savedThreads.value.filter(
    item => item.id !== target.id,
  );
  persistThreads();
  closeContextMenu();

  if (!deletingActiveThread) return;

  createNewThread();
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
  const index = messages.value.findIndex(existing => existing.id === message.id);
  if (index === -1) return;
  messages.value[index] = { ...messages.value[index], ...message };
};

const mergeMapLayers = (incoming: HazardMapLayer[]) => {
  const merged = new Map<string, HazardMapLayer>();
  [...mapLayers.value, ...incoming].forEach(layer => merged.set(layer.layer_id, layer));
  mapLayers.value = Array.from(merged.values());
  const newIds = incoming.map(l => l.layer_id).filter(id => !activeMapLayerIds.value.includes(id));
  activeMapLayerIds.value.push(...newIds);
};

const clearPendingInteraction = () => {
  isPausedWaitingForFeedback.value = false;
  pendingCheckpointId.value = null;
};

const appendInteractionMessage = (interaction: PendingInteraction) => {
  messages.value.push({
    role: 'assistant',
    content: interaction.kind === 'clarification'
      ? interaction.message
      : '',
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
  appendInteractionMessage(interaction);
};

const loadThreadState = async (id: string) => {
  try {
    const res = await fetch(`${API_BASE}/api/history/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error(`History request failed`);
    const data = await res.json();
    messages.value = data.messages || [];
    mapLayers.value = data.map_layers || [];
    activeMapLayerIds.value = mapLayers.value.map(l => l.layer_id);
    restorePendingInteraction(data.pending_interaction, data.checkpoint_id);
    isLoading.value = Boolean(data.is_running);
    connectionStatus.value = data.is_errored
      ? 'error'
      : data.is_running
        ? 'streaming'
        : 'idle';
    await scrollToBottom();

    if (data.is_running && threadId.value === id) {
      void subscribeToThread(id);
    }
  } catch (error) {
    connectionStatus.value = 'error';
  }
};

const applyStreamEvent = (data: InboundCommand) => {
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
    case 'map_layers':
      mergeMapLayers(data.layers || []);
      scrollToBottom();
      return;
    case 'custom_event':
      handleCustomEvent(data);
      return;
  }
};

const handleCustomEvent = (data: InboundCommand) => {
  if (data.type !== 'custom_event') return;
  if (data.name === 'reasoning_header') reasoningHeader.value = data.data;
  else if (data.name === 'fusion_start') {
    currentAssistantMessage().reasoning +=
      `\n\n**Fusing documents...**\n`;
  } else if (data.name === 'rerank_start') {
    currentAssistantMessage().reasoning +=
      `\n\n**Reranking documents...**\n\n`;
  }
}

const consumeEventStream = async (
  response: Response,
  expectedThreadId: string,
) => {
  if (!response.body) throw new Error('Stream response had no body');

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

      const dataLines = block.split(/\r?\n/)
        .filter(line => line.startsWith('data:'))
        .map(line => line.slice(5).trimStart());

      if (dataLines.length && threadId.value === expectedThreadId) {
        applyStreamEvent(JSON.parse(dataLines.join('\n')));
      }

      boundaryIndex = buffer.indexOf('\n\n');
    }
  }
};

const subscribeToThread = async (id: string) => {
  const controller = new AbortController();
  activeRequestController?.abort();
  activeRequestController = controller;

  try {
    const response = await fetch(
      `${API_BASE}/api/threads/${encodeURIComponent(id)}/events`,
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
  const expectedThreadId = threadId.value;

  try {
    const response = await fetch(`${API_BASE}/api/threads/${encodeURIComponent(expectedThreadId)}/commands`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(command),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Stream request failed (${response.status})`);
    }

    await consumeEventStream(response, expectedThreadId);
  } catch (error: any) {
    if (error.name === 'AbortError') return;
    if (threadId.value === expectedThreadId) connectionStatus.value = 'error';
  } finally {
    if (activeRequestController === controller) {
      activeRequestController = null;
      isLoading.value = false;
      if (connectionStatus.value === 'streaming') connectionStatus.value = 'idle';
    }
  }
};

const startQuery = () => {
  const query = userQuery.value.trim();
  if (!query || isLoading.value) return;

  const isResuming = isPausedWaitingForFeedback.value;

  messages.value.push({ role: 'user', content: query, reasoning: '', isReasoningExpanded: false });
  userQuery.value = '';
  nextTick(resizeQueryInput);

  if (!isResuming && !savedThreads.value.some(t => t.id === threadId.value)) {
    savedThreads.value.unshift({ id: threadId.value, title: query.substring(0, 40), date: Date.now() });
    persistThreads();
  }

  if (!isResuming) ensureAssistantPlaceholder();
  scrollToBottom();

  if (isPausedWaitingForFeedback.value) {
    const cpId = pendingCheckpointId.value;
    clearPendingInteraction();
    void streamCommand({ action: 'resume', response: query, checkpoint_id: cpId });
  } else {
    void streamCommand({ action: 'query', query, user_profile: usrPfp.value });
  }
};

const stopQuery = () => {
  activeRequestController?.abort();
  activeRequestController = null;
  isLoading.value = false;
  connectionStatus.value = 'idle';
};

onMounted(async () => {
  const stored = localStorage.getItem('chat_threads');
  if (stored) savedThreads.value = JSON.parse(stored);
  await loadThreadState(threadId.value);
});
</script>

<template>
  <div class="flex flex-col gap-1 h-screen w-full">
    <div class="relative flex h-[100vh] w-full min-h-0 flex-row">
      <ThreadSidebar :is-open="isThreadListOpen" :threads="savedThreads" :active-thread-id="threadId"
        :connection-status="connectionStatus" @close="isThreadListOpen = false" @open="isThreadListOpen = true"
        @create-new="createNewThread" @open-profile="openProfile" @select="closeContextMenu(); selectThread($event)"
        @context-menu="openContextMenu" />

      <button v-if="isThreadListOpen || isDocumentListOpen" type="button"
        class="fixed inset-0 z-40 bg-gray-900/30 lg:hidden" aria-label="Close side panels"
        @click="isThreadListOpen = false; isDocumentListOpen = false"></button>

      <!-- Chat -->
      <div
        class="mx-10 flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-x border-gray-200 bg-white lg:mx-auto">

        <!-- Messages -->
        <div class="flex-1 overflow-y-auto flex pt-4 flex-col gap-4" ref="messagesContainer" @scroll="handleScroll">
          <MessageItem v-for="(msg, index) in messages" :key="index" :msg="msg"
            :isGenerating="isLoading && index === messages.length - 1 && !isPausedWaitingForFeedback"
            :reasoningHeader="reasoningHeader" @update:reasoningExpanded="msg.isReasoningExpanded = $event"
            @open-plan="openDrawer('plan', $event)" @open-context="openDrawer('context', $event)" />
        </div>

        <!-- Inputs -->
        <div class="flex p-4 border-t border-gray-200 gap-2 bg-white items-end">
          <button v-if="mapLayers.length" type="button" @click="isMapOverlayOpen = true"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-gray-300 text-gray-600 transition-colors hover:border-blue-500 hover:bg-blue-50 hover:text-blue-600"
            aria-label="Open map" title="Open map">
            <MapIcon class="h-4 w-4" aria-hidden="true" />
          </button>

          <textarea ref="userQueryInput" v-model="userQuery" placeholder="Ask a question..." :disabled="isLoading"
            class="min-h-11 max-h-45 flex-1 resize-none overflow-y-auto rounded-lg border border-gray-300 px-4 py-2.5 leading-6 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed"
            @input="resizeQueryInput" @keydown.enter.exact.prevent="startQuery" rows="1"></textarea>

          <button v-if="isLoading" @click="stopQuery"
            class="h-11 shrink-0 rounded-xl bg-red-600 px-5 text-white transition-colors font-medium hover:bg-red-700">
            <Square class="mr-2 inline-block h-4 w-4 fill-current" aria-hidden="true" />
            Stop
          </button>

          <button v-else @click="startQuery" :disabled="!userQuery.trim()"
            class="h-11 shrink-0 rounded-xl bg-blue-600 px-5 text-white transition-colors font-medium hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500">
            <Send class="mr-2 inline-block h-4 w-4" aria-hidden="true" />
            Send
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
            <p class="text-sm text-gray-500 mt-1">Help the assistant tailor its answers to your role and preferences.
            </p>
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
    <MapOverlay :show="isMapOverlayOpen" :layers="mapLayers" :activeLayerIds="activeMapLayerIds"
      @update:activeLayers="activeMapLayerIds = $event" @close="isMapOverlayOpen = false" />

    <SideDrawer :isOpen="isDrawerOpen" :type="drawerType" :planData="drawerPlanData" :contextData="drawerContextData"
      @close="isDrawerOpen = false" />

    <ContextMenu :open="contextMenu.open" :x="contextMenu.x" :y="contextMenu.y"
      :thread-title="contextMenu.thread?.title" @close="closeContextMenu" @rename="renameContextThread"
      @delete="deleteContextThread" />
  </div>
</template>