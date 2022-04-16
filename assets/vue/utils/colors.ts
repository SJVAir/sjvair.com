export const Colors = {
  white: 'ffffff',
  gray: '969696',
  black: '000000',
  green: '00e400',
  yellow: 'ffff00',
  orange: 'ff7e00',
  red: 'ff0000',
  purple: '8f3f97',
  maroon: '7e0023'
} as const;

export const TextColors = new Map()
  .set(Colors.white, Colors.black)
  .set(Colors.gray, Colors.black)
  .set(Colors.black, Colors.white)
  .set(Colors.green, Colors.black)
  .set(Colors.yellow, Colors.black)
  .set(Colors.orange, Colors.white)
  .set(Colors.red, Colors.white)
  .set(Colors.purple, Colors.white)
  .set(Colors.maroon, Colors.white);

