<script setup lang="ts">
import { ref, watch, nextTick } from 'vue';
import type { Message, DisplayPlan } from '../types/app.ts';
import { renderMarkdown } from '../utils/markdown';
import { vMarkdown } from '../directives/markdown';
import PlanDisplay from './PlanDisplay.vue';
import { Check, ChevronDown, ClipboardList, Copy, Lightbulb, LoaderCircle, X } from '@lucide/vue';

const props = defineProps<{
    msg: Message;
    isGenerating: boolean;
    reasoningHeader: string;
}>();

const emit = defineEmits<{
    (e: 'update:reasoningExpanded', value: boolean): void;
    (e: 'open-plan', plan: DisplayPlan): void;
    (e: 'open-context', context: Record<string, string>): void;
}>();

const reasoningContainer = ref<HTMLDivElement | null>(null);
const reasoningAutoScrollEnabled = ref(true);
const isCopied = ref(false);

const handleScrollReasoning = () => {
    const el = reasoningContainer.value;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    reasoningAutoScrollEnabled.value = distanceFromBottom < 10;
};

const copyContent = async () => {
    if (!props.msg.content) return;

    try {
        await navigator.clipboard.writeText(props.msg.content);
        isCopied.value = true;

        setTimeout(() => {
            isCopied.value = false;
        }, 2000);
    } catch (err) {
        console.error('Failed to copy text', err);
    }
};

watch(() => props.msg.reasoning, async () => {
    if (!reasoningAutoScrollEnabled.value || !reasoningContainer.value) return;
    await nextTick();
    reasoningContainer.value.scrollTop = reasoningContainer.value.scrollHeight;
});
</script>

<template>
    <div class="mx-auto flex w-full max-w-4xl px-4" :class="msg.role === 'user' ? 'justify-end' : 'justify-center'">
        <div class="px-4 py-3 leading-relaxed overflow-hidden"
            :class="msg.role === 'user' ? 'max-w-[75%] bg-blue-600 text-white rounded-xl' : 'w-full bg-white rounded-tr-xl border-gray-200 text-gray-800'">

            <div v-if="msg.reasoning" class="text-sm mb-2 pb-2 border-b"
                :class="msg.role === 'user' ? 'border-blue-400' : 'border-gray-200'">

                <button @click="emit('update:reasoningExpanded', !msg.isReasoningExpanded)"
                    class="font-bold text-xs uppercase tracking-wider mb-2 flex items-center gap-1.5 w-full text-left cursor-pointer hover:opacity-75 transition-opacity focus:outline-none"
                    :class="msg.role === 'user' ? 'text-blue-200' : 'text-gray-500'">
                    <LoaderCircle v-if="isGenerating" class="h-4 w-4 animate-spin" aria-hidden="true" />
                    <Lightbulb v-else class="h-4 w-4" aria-hidden="true" />
                    <span :class="{ 'animate-pulse': isGenerating }">
                        {{ isGenerating ? reasoningHeader : (msg.isReasoningExpanded ? `Hide Reasoning` : `Show
                        Reasoning`) }}
                    </span>
                    <ChevronDown class="ml-auto h-4 w-4 transition-transform duration-200"
                        :class="msg.isReasoningExpanded ? 'rotate-180' : ''" aria-hidden="true" />
                </button>

                <div class="flex flex-col gap-2">
                    <div v-show="msg.isReasoningExpanded" ref="reasoningContainer" @scroll="handleScrollReasoning"
                        class="italic prose prose-sm max-w-none max-h-70 overflow-y-auto mt-2 border-l-1 border-gray-300 pl-5 ml-5"
                        :class="msg.role === 'user' ? 'prose-invert text-blue-100' : 'text-gray-500'"
                        v-markdown="renderMarkdown(msg.reasoning)"></div>
                    <div class="flex justify-end">
                        <button v-if="msg.isReasoningExpanded" @click="emit('update:reasoningExpanded', false)">
                            <span
                                class="flex items-center gap-1 text-xs underline underline-offset-4 text-gray-500 cursor-pointer">
                                <X class="h-3 w-3" aria-hidden="true" /> Close
                            </span>
                        </button>
                    </div>
                </div>
            </div>

            <div v-if="!msg.reasoning || msg.content" class="text-sm prose prose-sm max-w-none"
                :class="msg.role === 'user' ? 'prose-invert' : ''" v-markdown="renderMarkdown(msg.content)">
            </div>

            <div v-if="msg.interaction?.kind === 'plan_approval'" class="mt-3 pt-3 border-t border-gray-100">
                <PlanDisplay :plan="msg.interaction.display_plan" :showApproval="true" />
            </div>

            <ul v-if="msg.additional_kwargs?.feedback?.length" class="mt-2 space-y-1">
                <li v-for="(item, i) in msg.additional_kwargs.feedback" :key="i"
                    class="flex items-start gap-1.5 text-sm text-black italic" :title="item.question">
                    <span class="shrink-0">→</span>
                    <span>{{ item.answer }}</span>
                </li>
            </ul>

            <div class="flex gap-3 mt-4 pt-2 border-t px-1"
                :class="msg.role === 'user' ? 'border-blue-500/50' : 'border-gray-100'"
                v-if="msg.content || msg.additional_kwargs?.plan || msg.additional_kwargs?.retrieved_context">

                <button @click="copyContent" class="text-xs transition-colors font-medium flex items-center gap-1"
                    :class="[
                        msg.role === 'user' ? 'text-blue-100 hover:text-white' : 'text-gray-500 hover:text-blue-600',
                        isCopied ? '!text-green-400' : ''
                    ]">

                    <Copy v-if="!isCopied" class="h-3.5 w-3.5" aria-hidden="true" />
                    <Check v-else class="h-3.5 w-3.5" aria-hidden="true" />

                    <span>{{ isCopied ? 'Copied!' : 'Copy' }}</span>
                </button>

                <button v-if="msg.additional_kwargs?.plan && msg.role === 'user'"
                    @click="emit('open-plan', msg.additional_kwargs.plan)"
                    class="text-xs transition-colors font-medium flex items-center gap-1"
                    :class="msg.role === 'user' ? 'text-blue-100 hover:text-white' : 'text-gray-500 hover:text-blue-600'">
                    <ClipboardList class="h-3.5 w-3.5" aria-hidden="true" />
                    Plan
                </button>

                <button v-if="msg.additional_kwargs?.retrieved_context && msg.role === 'user'"
                    @click="emit('open-context', msg.additional_kwargs.retrieved_context)"
                    class="text-xs transition-colors font-medium flex items-center gap-1"
                    :class="msg.role === 'user' ? 'text-blue-100 hover:text-white' : 'text-gray-500 hover:text-blue-600'">
                    <ClipboardList class="h-3.5 w-3.5" aria-hidden="true" />
                    Context
                </button>
            </div>
        </div>
    </div>
</template>