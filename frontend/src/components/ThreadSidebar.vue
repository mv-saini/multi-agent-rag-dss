<script setup lang="ts">
import type { ChatThread } from '../types/app.ts';
import { Ellipsis, PanelLeftClose, PanelLeftOpen, Plus, UserRound } from '@lucide/vue';

defineProps<{
    isOpen: boolean;
    threads: ChatThread[];
    activeThreadId: string;
    connectionStatus: 'idle' | 'streaming' | 'error';
}>();

const emit = defineEmits<{
    (event: 'close'): void;
    (event: 'open'): void;
    (event: 'create-new'): void;
    (event: 'open-profile'): void;
    (event: 'select', threadId: string): void;
    (event: 'context-menu', mouseEvent: MouseEvent, thread: ChatThread): void;
}>();
</script>

<template>
    <aside v-if="isOpen"
        class="fixed inset-y-0 left-0 z-50 flex h-full w-[min(20rem,calc(100vw-2rem))] shrink-0 flex-col overflow-hidden bg-white shadow-xl lg:static lg:z-auto lg:w-72 lg:rounded-xl lg:shadow-none"
        aria-label="Conversations">
        <header class="flex items-center justify-between px-3 py-2">
            <h2 class="text-lg font-semibold text-gray-800">Demo</h2>
            <div class="flex items-center gap-2">
                <span class="rounded-full px-2 py-1 text-[10px] font-medium uppercase tracking-wide" :class="{
                    'bg-green-100 text-green-800': connectionStatus === 'idle',
                    'bg-yellow-100 text-yellow-800': connectionStatus === 'streaming',
                    'bg-red-100 text-red-800': connectionStatus === 'error'
                }">
                    {{ connectionStatus }}
                </span>
                <button type="button"
                    class="flex h-9 w-9 items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
                    aria-label="Close conversations" title="Close conversations" @click="emit('close')">
                    <PanelLeftClose class="h-5 w-5" aria-hidden="true" />
                </button>
            </div>
        </header>

        <div class="px-1">
            <button type="button" @click="emit('create-new')"
                class="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-semibold text-gray-700 transition-colors hover:bg-blue-100">
                <Plus class="h-4 w-4" aria-hidden="true" />
                New Conversation
            </button>
            <button type="button" @click="emit('open-profile')"
                class="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-semibold text-gray-700 transition-colors hover:bg-blue-100">
                <UserRound class="h-4 w-4" aria-hidden="true" />
                Edit Profile
            </button>
        </div>

        <div class="flex items-center justify-between px-3 py-4">
            <p class="text-xs font-semibold uppercase tracking-widest text-gray-600">Conversations</p>
        </div>


        <div class="flex-1 overflow-y-auto px-3">
            <div v-if="!threads.length" class="px-3 py-10 text-center text-sm text-gray-500">
                No conversations yet.
            </div>

            <div v-else class="space-y-0.5">
                <div v-for="thread in threads" :key="thread.id"
                    class="group cursor-pointer p-1.5 transition-colors hover:bg-blue-100 hover:rounded-lg"
                    :class="thread.id === activeThreadId ? 'bg-blue-100 rounded-lg' : ''"
                    @click="emit('select', thread.id)" @contextmenu="emit('context-menu', $event, thread)">
                    <div class="flex items-start justify-between gap-2">
                        <h3 class="min-w-0 flex-1 truncate text-sm font-medium text-gray-800">{{ thread.title }}</h3>
                        <button type="button"
                            class="shrink-0 rounded p-0.5 text-gray-400 opacity-0 transition-opacity hover:text-gray-700 group-hover:opacity-100"
                            aria-label="Conversation actions" title="Conversation actions"
                            @click.stop="emit('context-menu', $event, thread)">
                            <Ellipsis class="h-4 w-4" aria-hidden="true" />
                        </button>
                    </div>
                    <!-- <span class="mt-2 block text-xs text-gray-500">{{ new Date(thread.date).toLocaleDateString('it-IT')
                    }}</span> -->
                </div>
            </div>
        </div>
    </aside>

    <div v-else
        class="fixed inset-y-0 left-0 z-50 flex h-full w-10 shrink-0 flex-col items-center bg-white py-2 shadow-lg lg:static lg:z-auto lg:shadow-none">
        <button type="button" @click="emit('open')"
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
            aria-label="Open conversations" title="Open conversations">
            <PanelLeftOpen class="h-5 w-5" aria-hidden="true" />
        </button>
        <button type="button" @click="emit('create-new')"
            class="mt-3 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-gray-700 transition-colors hover:bg-blue-100"
            aria-label="New conversation" title="New conversation">
            <Plus class="h-5 w-5" aria-hidden="true" />
        </button>
        <button type="button" @click="emit('open-profile')"
            class="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-gray-700 transition-colors hover:bg-blue-100"
            aria-label="Edit profile" title="Edit profile">
            <UserRound class="h-4 w-4" aria-hidden="true" />
        </button>
    </div>
</template>