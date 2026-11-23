<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch, nextTick } from 'vue';
import type { CitationSource, Message, DisplayPlan, EvidenceBundle } from '@/types/app.ts';
import { renderMarkdown } from '@/utils/markdown';
import { vMarkdown } from '@/directives/markdown';
import PlanDisplay from '@/components/PlanDisplay.vue';
import { ArrowUpRight, Check, ChevronDown, ClipboardList, Copy, Lightbulb, LoaderCircle, MapPin, X } from '@lucide/vue';

const props = defineProps<{
    msg: Message;
    evidence?: EvidenceBundle;
    isGenerating: boolean;
    reasoningHeader: string;
    canEditScenario?: boolean;
    canApprovePlan?: boolean;
    loadingEvidence?: boolean;
}>();

const emit = defineEmits<{
    (e: 'update:reasoningExpanded', value: boolean): void;
    (e: 'open-plan', plan: DisplayPlan): void;
    (e: 'open-context', context: Record<string, string>): void;
    (e: 'open-scenario'): void;
    (e: 'approve-plan'): void;
}>();

const reasoningContainer = ref<HTMLDivElement | null>(null);
const reasoningAutoScrollEnabled = ref(true);
const isCopied = ref(false);
const feedbackQuestion = ref('');
const feedbackQuestionPosition = ref({ left: '0px', top: '0px', transform: '' });
const showFeedbackQuestion = (event: Event, question: string) => {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const width = Math.min(360, window.innerWidth - 24);
    const above = rect.top > window.innerHeight / 2;
    feedbackQuestionPosition.value = {
        left: `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`,
        top: `${above ? rect.top - 8 : rect.bottom + 8}px`,
        transform: above ? 'translateY(-100%)' : '',
    };
    feedbackQuestion.value = question;
};
const activeCitation = ref<CitationSource | null>(null);
const citationPosition = ref({ left: '0px', top: '0px' });
let citationHideTimer: number | undefined;

const citationSources = computed(
    () => props.evidence?.citation_sources ?? {},
);

const retrievedContext = computed(
    () => props.evidence?.retrieved_context,
);
const isContextLoading = computed(() => Boolean(
    props.loadingEvidence && props.msg.additional_kwargs?.evidence_bundle_id && !props.evidence,
));
const displayPlan = computed(() => {
    const plan = props.msg.additional_kwargs?.plan;
    return plan && props.evidence ? { ...plan, web_results: props.evidence.web_results } : plan;
});

const citationButton = (event: Event): HTMLElement | null => {
    const target = event.target;
    return target instanceof Element
        ? target.closest<HTMLElement>('[data-citation-id]')
        : null;
};

const clearCitationHideTimer = () => {
    if (citationHideTimer !== undefined) window.clearTimeout(citationHideTimer);
    citationHideTimer = undefined;
};

const showCitation = (button: HTMLElement) => {
    const sourceId = button.dataset.citationId;
    const source = sourceId ? citationSources.value[sourceId] : undefined;
    if (!source) return;

    clearCitationHideTimer();
    const rect = button.getBoundingClientRect();
    const width = Math.min(360, window.innerWidth - 24);
    const left = Math.min(
        Math.max(12, rect.left),
        Math.max(12, window.innerWidth - width - 12),
    );
    const estimatedHeight = 260;
    const below = rect.bottom + 8;
    const top = below + estimatedHeight <= window.innerHeight
        ? below
        : Math.max(12, rect.top - estimatedHeight - 8);

    activeCitation.value = source;
    citationPosition.value = { left: `${left}px`, top: `${top}px` };
};

const scheduleCitationHide = () => {
    clearCitationHideTimer();
    citationHideTimer = window.setTimeout(() => {
        activeCitation.value = null;
    }, 150);
};

const handleCitationMouseOver = (event: Event) => {
    const button = citationButton(event);
    if (button) showCitation(button);
};

onBeforeUnmount(() => {
    clearCitationHideTimer();
});

const handleScrollReasoning = () => {
    const el = reasoningContainer.value;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    reasoningAutoScrollEnabled.value = distanceFromBottom < 10;
};

const copyContent = async () => {
    if (!props.msg.content) return;

    const copyText = props.msg.content.replace(
        /\[\[CITE:([A-Za-z0-9_-]+)\]\]/g,
        (_match, sourceId: string) => {
            const source = citationSources.value[sourceId];
            return source ? `[${source.label}]` : '';
        },
    );

    try {
        await navigator.clipboard.writeText(copyText);
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

            <div v-if="msg.reasoning || isGenerating" class="text-sm mb-2 pb-2 border-b"
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
                                <X class="h-3 w-3" aria-hidden="true" />
                            </span>
                        </button>
                    </div>
                </div>
            </div>

            <div v-if="!msg.reasoning || msg.content" class="text-sm prose prose-sm max-w-none"
                :class="msg.role === 'user' ? 'prose-invert' : ''" @mouseover="handleCitationMouseOver"
                @mouseout="scheduleCitationHide" @focusin="handleCitationMouseOver" @focusout="scheduleCitationHide"
                v-markdown="renderMarkdown(msg.content, citationSources)">
            </div>

            <div v-if="msg.interaction?.kind === 'plan_approval'" class="mt-3 pt-3 border-t border-gray-100">
                <PlanDisplay :plan="msg.interaction.display_plan" :showApproval="canApprovePlan"
                    @approve="emit('approve-plan')" />
            </div>

            <button v-if="canEditScenario" type="button" @click="emit('open-scenario')"
                class="group mt-4 flex w-full max-w-md items-center gap-3 rounded-xl border border-gray-200 bg-white p-3.5 text-left transition-colors hover:border-gray-300 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
                <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-600">
                    <MapPin class="h-5 w-5" aria-hidden="true" />
                </span>
                <span class="min-w-0 flex-1">
                    <span class="block text-sm font-medium text-gray-900">Earthquake scenario</span>
                    <span class="mt-0.5 block text-xs text-gray-500">Choose a fault, shaking parameters, and area</span>
                </span>
                <ArrowUpRight class="h-4 w-4 shrink-0 text-gray-400 group-hover:text-gray-700" aria-hidden="true" />
            </button>

            <ul v-if="msg.additional_kwargs?.feedback?.length" class="mt-2 space-y-1">
                <li v-for="(item, i) in msg.additional_kwargs.feedback" :key="i"
                    class="flex items-start gap-1.5 text-sm text-black italic" tabindex="0"
                    @mouseenter="showFeedbackQuestion($event, item.question)" @mouseleave="feedbackQuestion = ''"
                    @focus="showFeedbackQuestion($event, item.question)" @blur="feedbackQuestion = ''"
                    @keydown.esc="feedbackQuestion = ''">
                    <span class="shrink-0">→</span>
                    <span>{{ item.answer }}</span>
                </li>
            </ul>

            <div class="flex gap-3 mt-4 pt-2 border-t px-1"
                :class="msg.role === 'user' ? 'border-blue-500/50' : 'border-gray-100'"
                v-if="msg.content || displayPlan || retrievedContext || (isContextLoading && msg.role === 'user')">

                <button @click="copyContent" class="text-xs transition-colors font-medium flex items-center gap-1"
                    :class="[
                        msg.role === 'user' ? 'text-blue-100 hover:text-white' : 'text-gray-500 hover:text-blue-600',
                        isCopied ? '!text-green-400' : ''
                    ]">

                    <Copy v-if="!isCopied" class="h-3.5 w-3.5" aria-hidden="true" />
                    <Check v-else class="h-3.5 w-3.5" aria-hidden="true" />

                    <span>{{ isCopied ? 'Copied!' : 'Copy' }}</span>
                </button>

                <button v-if="displayPlan && msg.role === 'user'" @click="emit('open-plan', displayPlan)"
                    class="text-xs transition-colors font-medium flex items-center gap-1"
                    :class="msg.role === 'user' ? 'text-blue-100 hover:text-white' : 'text-gray-500 hover:text-blue-600'">
                    <ClipboardList class="h-3.5 w-3.5" aria-hidden="true" />
                    Plan
                </button>

                <span v-if="isContextLoading && msg.role === 'user'" role="status"
                    class="text-xs transition-colors font-medium flex items-center gap-1 text-blue-100">
                    <LoaderCircle class="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden="true" />
                    Loading context...
                </span>
                <button v-else-if="retrievedContext && msg.role === 'user'"
                    @click="emit('open-context', retrievedContext)"
                    class="text-xs transition-colors font-medium flex items-center gap-1 text-blue-100 hover:text-white">
                    <ClipboardList class="h-3.5 w-3.5" aria-hidden="true" />
                    Context
                </button>

            </div>
        </div>
    </div>

    <Teleport to="body">
        <div v-if="feedbackQuestion" role="tooltip" :style="feedbackQuestionPosition"
            class="pointer-events-none fixed z-[100] max-h-[40vh] w-[min(360px,calc(100vw-24px))] overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-gray-900 p-3 text-sm text-white shadow-lg">
            {{ feedbackQuestion }}
        </div>
        <div v-if="activeCitation" role="tooltip" :aria-label="`Citation ${activeCitation.label}`"
            class="fixed z-[100] w-[min(600px,calc(100vw-24px))] rounded-lg border border-gray-200 bg-white p-3 text-sm text-gray-800 shadow-xl"
            :style="citationPosition" @mouseenter="clearCitationHideTimer" @mouseleave="scheduleCitationHide">
            <div>
                <div class="text-xs font-semibold uppercase tracking-wide text-blue-600">
                    {{ activeCitation.kind }} · Citation {{ activeCitation.label }}
                </div>
                <div class="mt-1 font-semibold leading-snug">{{ activeCitation.title }}</div>
                <div v-if="activeCitation.page !== null && activeCitation.page !== undefined"
                    class="mt-0.5 text-xs text-gray-500">
                    Page {{ activeCitation.page }}
                </div>
            </div>

            <div class="prose prose-sm mt-3 max-h-52 max-w-none overflow-y-auto rounded-md border border-yellow-200 bg-yellow-50 p-3 text-sm leading-relaxed text-gray-800"
                v-markdown="renderMarkdown(activeCitation.text)"></div>

            <a v-if="activeCitation.url" :href="activeCitation.url" target="_blank" rel="noopener noreferrer"
                class="mt-2 inline-flex text-xs font-medium text-blue-600 hover:underline">
                Open source
            </a>
        </div>
    </Teleport>
</template>
