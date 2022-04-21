import { dateUtil } from "../utils";

export class DateRange extends Array<string> {

  constructor(range?: DateRange) {
    let start: string = dateUtil.dayjs().subtract(3, "day").startOf("day").toISOString();
    let end: string = dateUtil.dayjs().endOf("day").toISOString();
    if (range) {
      start = dateUtil.dayjs(range.start).startOf("day").toISOString();
      end = dateUtil.dayjs(range.end).endOf("day").toISOString();
    }
    super(start, end);
  }

  get start() {
    return this[0];
  }

  set start(date: string) {
    this.splice(0, 1, dateUtil.dayjs(date).startOf("day").toISOString());
  }

  get end() {
    return this[1];
  }

  set end(date: string) {
    this.splice(1, 1, dateUtil.dayjs(date).endOf("day").toISOString());
  }
}
