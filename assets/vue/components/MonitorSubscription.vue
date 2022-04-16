<script setup lang="ts">
import { computed, inject, onMounted, Ref, ref, watch } from "vue";
import { SubscriptionLevel } from "../models";
import { http } from "../utils"
import type { IMonitorSubscription } from "../types";
import type { MonitorsService } from "../services";

//const defaultSelection = "Subscribe";

// Reference to current active monitor
const monitorsService = inject<MonitorsService>("MonitorsService")!;
// Dropdown display value
//const selection = defaultSelection;
// Select element options
const subscriptionOptions: Ref<HTMLElement> = ref(null!);
// User is authenticated
const validUser = (window as any).USER.is_authenticated


// Change button text if user is subscribed
const buttonText = computed(() => subscribed ? "Manage Subscription" : "Subscribe To Alerts")

// Dropdown state
let active = false;
// Subscription status
let subscribed = false;
// Subscription Levels
let subscriptionLevels = [
  new SubscriptionLevel("unhealthy_sensitive", "#D4712B"),
  new SubscriptionLevel("unhealthy", "#C3281C"),
  new SubscriptionLevel("very_unhealthy", "#66567E"),
  new SubscriptionLevel("hazardous", "#653734")
];

function formatDataStr(data_str: string) {
  if (!data_str) {
    return "";
  }

  return data_str.split("_")
    .map(str => str.charAt(0).toUpperCase() + str.slice(1))
    .join(" ");
}

function hideUnsubscribe(target: HTMLElement, selectedLevel: SubscriptionLevel) {
  if (selectedLevel.subscribed && target.innerText === "Unsubscribe") {
    target.innerText = formatDataStr(selectedLevel.levelName);
    target.style.textAlign = "left";
  }
}

async function loadSubscriptions() {
  let subscription;

  if ("USER" in window && (window as any).USER.is_authenticated) {
    const subscriptions = await monitorsService.loadSubscriptions();

    if (subscriptions) {
      subscription = subscriptions.find(s => s.monitor === monitorsService.activeMonitor!.data.id);
    }
  }

  if (subscription) {
    update(subscription.level);

  } else {
    update(null);
  }
}

function selectOption(target: HTMLElement, selectedLevel: SubscriptionLevel) {
  update(selectedLevel.levelName);

  if (target.innerText === "Unsubscribe") {
    unsubscribe(selectedLevel.levelName);
    target.innerText = selectedLevel.display;
    target.style.textAlign = "left";

  } else {
    subscribe(selectedLevel.levelName);
  }

  // close dropdown
  active = false;
}

function showUnsubscribe(target: HTMLElement, selectedLevel: SubscriptionLevel) {
  if (selectedLevel.subscribed && target.innerText !== "Unsubscribe") {
    target.style.textAlign = "center";
    target.innerText = "Unsubscribe";
  }
}

function subscribe(level: IMonitorSubscription["level"]) {
  http.post(`monitors/${ monitorsService.activeMonitor!.data.id }/alerts/subscribe/`, { level })
    .catch(err => console.error("Failed to subscribe", err));
}

function toggleDropdown() {
  active = !active;
}

function unsubscribe(level: IMonitorSubscription["level"]) {
  http.post(`monitors/${ monitorsService.activeMonitor!.data.id }/alerts/unsubscribe/`, { level })
    .catch(err => console.error("Failed to unsubscribe", err));
}

function update(level: IMonitorSubscription["level"] | null) {
  subscriptionLevels = subscriptionLevels.map(sub => {
    if (sub.levelName === level) {
      sub.subscribed = !sub.subscribed;

    } else {
      sub.subscribed = false;
    }

    return sub;
  });

  subscribed = !subscriptionLevels.every(sub => sub.subscribed === false);
}


watch(
  () => monitorsService.activeMonitor,
  () => {
    active = false;
    loadSubscriptions();
  }
);

onMounted(() => {
  // This is kind of a dirty hack to force keep the initial width of
  // the dropdown options, but it's 2am;
  if (subscriptionOptions.value) {
    const optionsRect = subscriptionOptions.value.getBoundingClientRect();
    subscriptionOptions.value.style.width = `${ optionsRect.width + 10 }px`
    loadSubscriptions();
  }
});
</script>

<template>
  <div v-if="validUser" class="monitor-subscription-wrapper">
    <div class="monitor-subscription-container">

      <button @click="toggleDropdown" :class="[{ 'is-success': subscribed }, 'is-info']"
        class="button is-small monitor-subscription-button">
        {{ buttonText }} <i :class="[{ 'fa-angle-up': active }, 'fa-angle-down']" class="fas"></i>
      </button>

      <div ref="subscriptionOptions" :class="{ active }" class="monitor-subscription-options">
        <p v-for="(level, index) of subscriptionLevels" :key="index"
          @click="e => selectOption(e.target as HTMLElement, level)"
          @mouseover="e => showUnsubscribe(e.target as HTMLElement, level)"
          @mouseleave="e => hideUnsubscribe(e.target as HTMLElement, level)"
          :style="{ backgroundColor: level.bgColor }"
          :class="{ subscribed: level.subscribed }" class="monitor-subscription-option">
          {{ level.display }}
        </p>
      </div>

    </div>
  </div>
</template>

