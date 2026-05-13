import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import TendersView from '@/views/TendersView.vue'
import MatchesView from '@/views/MatchesView.vue'
import EmailsView from '@/views/EmailsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/tenders', name: 'tenders', component: TendersView },
    { path: '/matches', name: 'matches', component: MatchesView },
    { path: '/emails', name: 'emails', component: EmailsView },
  ],
})

export default router
