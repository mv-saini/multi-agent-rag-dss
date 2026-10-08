import type { DirectiveBinding } from 'vue';

export const vMarkdown = {
  mounted(el: HTMLElement, binding: DirectiveBinding) {
    el.innerHTML = binding.value || '';
  },
  updated(el: HTMLElement, binding: DirectiveBinding) {
    if (binding.value !== binding.oldValue) {
      const preElements = el.querySelectorAll('pre');
      const scrollStates = Array.from(preElements).map(node => ({
        scrollLeft: node.scrollLeft,
        scrollTop: node.scrollTop
      }));

      el.innerHTML = binding.value || '';

      const newPreElements = el.querySelectorAll('pre');
      scrollStates.forEach((state, i) => {
        if (newPreElements[i]) {
          newPreElements[i].scrollLeft = state.scrollLeft;
          newPreElements[i].scrollTop = state.scrollTop;
        }
      });
    }
  }
};