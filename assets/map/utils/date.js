import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';

// Add the plugins we need
dayjs.extend(relativeTime);
dayjs.extend(timezone);
dayjs.extend(utc);

// Define custom date utils
Object.assign(dayjs, {
  $defaultFormat(date) {
    return dayjs.utc(date).format('YYYY-MM-DD HH:mm:ss');
  }
});

export default dayjs;
