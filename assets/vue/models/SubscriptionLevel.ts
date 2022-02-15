import { IMonitorSubscription } from "../types";

export class SubscriptionLevel {
  levelName: IMonitorSubscription["level"];
  bgColor: string;
  subscribed: boolean = false;
  display: string;

  constructor(levelName: IMonitorSubscription["level"], bgColor: string) {
      this.levelName = levelName;
      this.bgColor = bgColor;
      this.subscribed = false;
      this.display = levelName.split("_")
        .map(str => str.charAt(0).toUpperCase() + str.slice(1))
        .join(" ");
    }
}
