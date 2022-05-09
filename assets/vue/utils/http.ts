import Axios from 'axios';

export const http = Axios.create({
  baseURL: '/api/1.0/',
});
