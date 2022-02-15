import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';

// Add the plugins we need
dayjs.extend(relativeTime);
dayjs.extend(timezone);
dayjs.extend(utc);

export default {
  dayjs,
  $defaultFormat(date: string | Date | dayjs.Dayjs) {
    return dayjs.utc(date).format("YYYY-MM-DD HH:mm:ss");
  },
  $prettyPrint(date: string | Date | dayjs.Dayjs) {
    return dayjs(date).format("h:mma dddd MMM DD, YYYY")
  }
};
