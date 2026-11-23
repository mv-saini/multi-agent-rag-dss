
import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

import Chat from '@/views/Chat.vue';
import Users from '@/views/Users.vue';
import Login from '@/views/Login.vue';
import ResetPassword from '@/views/ResetPassword.vue';
import Document from '@/views/Document.vue';

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: Login,
      meta: { requiresAuth: false },
    },
    {
      path: '/reset-password',
      name: 'reset-password',
      component: ResetPassword,
      meta: { requiresAuth: true },
    },
    {
      path: '/',
      name: 'home',
      component: Chat,
      meta: { requiresAuth: true },
    },
    {
      path: '/users',
      name: 'users',
      component: Users,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: '/documents/:id/parsed',
      name: 'parsed-document',
      component: Document,
      meta: { requiresAuth: true },
    },
  ],
});

router.beforeEach(async (to) => {
  const authStore = useAuthStore();
  const requiresAuth = to.matched.some(
    (record) => record.meta.requiresAuth,
  );
  const requiresAdmin = to.matched.some(
    (record) => record.meta.requiresAdmin,
  );

  if (authStore.user === null && !authStore.loggedOut) {
    await authStore.checkAuthStatus();
  }

  if (requiresAuth && !authStore.isAuthenticated) {
    return { name: 'login' };
  }

  if (authStore.requireReset && to.name !== 'reset-password') {
    return { name: 'reset-password' };
  }

  if (to.name === 'reset-password' && !authStore.requireReset) {
    return { name: 'home' };
  }

  if (requiresAdmin && !authStore.isAdmin) {
    return { name: 'home' };
  }

  if (to.name === 'login' && authStore.isAuthenticated) {
    return { name: 'home' };
  }

  return true;
});

export default router;
