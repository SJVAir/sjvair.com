import { dateUtil } from "../utils";
import { Dayjs } from "dayjs";

export class DateRange {
  start: Dayjs = dateUtil.dayjs().subtract(3, "day").startOf("day");
  end: Dayjs = dateUtil.dayjs().endOf("day");

  constructor(range?: DateRange) {
    if (range) {
      this.start = dateUtil.dayjs(range.start).startOf("day");
      this.end = dateUtil.dayjs(range.end).endOf("day");
    }
  }
}
