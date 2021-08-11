
<template>
  <div v-if="validUser" class="monitor-subscription-wrapper">
    <div class="monitor-subscription-container">

      <button @click="toggleDropdown" :class="[{ 'is-success': subscribed }, 'is-info']"
        class="button is-small monitor-subscription-button">
        {{ buttonText }} <i :class="[{ 'fa-angle-up': active }, 'fa-angle-down']" class="fas"></i>
      </button>

      <div ref="subscriptionOptions" :class="{ active }" class="monitor-subscription-options">
        <p v-for="(level, index) of subscriptionLevels" :key="index"
          @click="e => selectOption(e.target, level)"
          @mouseover="e => showUnsubscribe(e.target, level)"
          @mouseleave="e => hideUnsubscribe(e.target, level)"
          :style="{ backgroundColor: level.bgColor }"
          :class="{ subscribed: level.subscribed }" class="monitor-subscription-option">
          {{ level.display }}
        </p>
      </div>

    </div>
  </div>
</template>

<script>
import monitorsService from "../services/Monitors.service";

const defaultSelection = "Subscribe";

class SubscriptionLevel {
  constructor(raw, bgColor) {
      this.raw = raw;
      this.bgColor = bgColor;
      this.subscribed = false;
      this.display = raw.split("_")
        .map(str => str.charAt(0).toUpperCase() + str.slice(1))
        .join(" ");
    }
}

const subscriptionLevels = [
  new SubscriptionLevel("unhealthy_sensitive", "#D4712B"),
  new SubscriptionLevel("unhealthy", "#C3281C"),
  new SubscriptionLevel("very_unhealthy", "#66567E"),
  new SubscriptionLevel("hazardous", "#653734")
];

export default {
  name: "monitor-subscription",

  data() {
    return {
      // Dropdown state
      active: false,
      // Component context
      ctx: monitorsService,
      // Dropdown display value
      selection: defaultSelection,
      // Subscription status
      subscribed: false,
      // Subscription Levels
      subscriptionLevels,
      // User is authenticated
      validUser: window.USER.is_authenticated
    };
  },

  computed: {
    activeMonitor() { return this.ctx.activeMonitor; },
    buttonText() { return !this.subscribed ? "Subscribe To Alerts" : "Manage Subscription"}
  },

  filters: {
    formatDataStr(data_str) {
      if (!data_str) {
        return;
      }

      return data_str.split("_")
        .map(str => str.charAt(0).toUpperCase() + str.slice(1))
        .join(" ");
    }
  },

  watch: {
    activeMonitor: function() {
      this.loadSubscriptions();
    }
  },

  mounted() {
    // This is kind of a dirty hack to force keep the initial width of
    // the dropdown options, but it's 2am;
    if (this.$refs.subscriptionOptions) {
      const optionsRect = this.$refs.subscriptionOptions.getBoundingClientRect();
      this.$refs.subscriptionOptions.style.width = `${ optionsRect.width + 10 }px`
      this.loadSubscriptions();
    }
  },

  methods: {
    hideUnsubscribe(target, selectedLevel) {
      if (selectedLevel.subscribed && target.innerText === "Unsubscribe") {
        target.innerText = this.$options.filters.formatDataStr(selectedLevel.raw);
        target.style.textAlign = "left";
      }
    },

    async loadSubscriptions() {
        const subscriptions = await this.ctx.loadSubscriptions();

        for (let subscription of subscriptions) {
          if (subscription.monitor === this.activeMonitor.id) {
            //this.subscribed = true;
            this.update(subscription.level);
          } else {
            //this.subscribed = false;
            this.update(null);
          }
        }
      },

    selectOption(target, selectedLevel) {
      this.update(selectedLevel.raw);

      if (target.innerText === "Unsubscribe") {
        this.unsubscribe(selectedLevel.raw);
        target.innerText = selectedLevel.display;
        target.style.textAlign = "left";

      } else {
        this.subscribe(selectedLevel.raw);
      }

      // close dropdown
      this.active = false;
    },

    showUnsubscribe(target, selectedLevel) {
      if (selectedLevel.subscribed && target.innerText !== "Unsubscribe") {
        target.style.textAlign = "center";
        target.innerText = "Unsubscribe";
      }
    },

    subscribe(level) {
      this.$http.post(`monitors/${ this.activeMonitor.id }/alerts/subscribe/`, { level })
        .catch(err => console.error("Failed to subscribe", err));
    },

    toggleDropdown() {
      this.active = !this.active;
    },

    unsubscribe(level) {
      this.$http.post(`monitors/${ this.activeMonitor.id }/alerts/unsubscribe/`, { level })
        .catch(err => console.error("Failed to unsubscribe", err));
    },

    update(rawLevel) {
      this.subscriptionLevels = this.subscriptionLevels.map(level => {
        if (level.raw === rawLevel) {

          level.subscribed = !level.subscribed;
          this.subscribed = level.subscribed;
        } else {
          level.subscribed = false;
        }

        return level;
      });
    }
  }
}
</script>
