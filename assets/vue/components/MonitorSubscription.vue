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

//export default {
//  name: "monitor-subscription",
//
//  data() {
//    return {
//      // Dropdown state
//      active: false,
//      // Component context
//      ctx: monitorsService,
//      // Dropdown display value
//      selection: defaultSelection,
//      // Subscription status
//      subscribed: false,
//      // Subscription Levels
//      subscriptionLevels,
//      // User is authenticated
//      validUser: window.USER.is_authenticated
//    };
//  },
//
//  computed: {
//    activeMonitor() { return this.ctx.activeMonitor; },
//    buttonText() { return !this.subscribed ? "Subscribe To Alerts" : "Manage Subscription"}
//  },
//
//  filters: {
//    formatDataStr(data_str) {
//      if (!data_str) {
//        return;
//      }
//
//      return data_str.split("_")
//        .map(str => str.charAt(0).toUpperCase() + str.slice(1))
//        .join(" ");
//    }
//  },
//
//  watch: {
//    activeMonitor: function() {
//      this.active = false;
//      this.loadSubscriptions();
//    }
//  },
//
//  mounted() {
//    // This is kind of a dirty hack to force keep the initial width of
//    // the dropdown options, but it's 2am;
//    if (this.$refs.subscriptionOptions) {
//      const optionsRect = this.$refs.subscriptionOptions.getBoundingClientRect();
//      this.$refs.subscriptionOptions.style.width = `${ optionsRect.width + 10 }px`
//      this.loadSubscriptions();
//    }
//  },
//
//  methods: {
//    hideUnsubscribe(target, selectedLevel) {
//      if (selectedLevel.subscribed && target.innerText === "Unsubscribe") {
//        target.innerText = this.$options.filters.formatDataStr(selectedLevel.raw);
//        target.style.textAlign = "left";
//      }
//    },
//
//    async loadSubscriptions() {
//      let subscription;
//
//      if ("USER" in window && window.USER.is_authenticated) {
//        const subscriptions = await this.ctx.loadSubscriptions();
//        subscription = subscriptions.find(s => s.monitor === this.activeMonitor.id);
//      }
//
//      if (subscription) {
//        this.update(subscription.level);
//
//      } else {
//        this.update(null);
//      }
//    },
//
//    selectOption(target, selectedLevel) {
//      this.update(selectedLevel.raw);
//
//      if (target.innerText === "Unsubscribe") {
//        this.unsubscribe(selectedLevel.raw);
//        target.innerText = selectedLevel.display;
//        target.style.textAlign = "left";
//
//      } else {
//        this.subscribe(selectedLevel.raw);
//      }
//
//      // close dropdown
//      this.active = false;
//    },
//
//    showUnsubscribe(target, selectedLevel) {
//      if (selectedLevel.subscribed && target.innerText !== "Unsubscribe") {
//        target.style.textAlign = "center";
//        target.innerText = "Unsubscribe";
//      }
//    },
//
//    subscribe(level) {
//      this.$http.post(`monitors/${ this.activeMonitor.id }/alerts/subscribe/`, { level })
//        .catch(err => console.error("Failed to subscribe", err));
//    },
//
//    toggleDropdown() {
//      this.active = !this.active;
//    },
//
//    unsubscribe(level) {
//      this.$http.post(`monitors/${ this.activeMonitor.id }/alerts/unsubscribe/`, { level })
//        .catch(err => console.error("Failed to unsubscribe", err));
//    },
//
//    update(rawLevel) {
//      this.subscriptionLevels = this.subscriptionLevels.map(level => {
//        if (level.raw === rawLevel) {
//          level.subscribed = !level.subscribed;
//
//        } else {
//          level.subscribed = false;
//        }
//
//        return level;
//      });
//
//      this.subscribed = !this.subscriptionLevels.every(level => level.subscribed === false);
//    }
//  }
//}
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

