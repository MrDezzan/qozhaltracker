# Картинки для лендинга

Промпты на английском: генераторы обучены на английских подписях, а
русский они переводят внутри себя и теряют именно то, что здесь важно —
время суток, положение камеры, пустое место под заголовок.

## Общий блок: вставлять в каждый промпт

Он отвечает за то, чтобы все картинки выглядели одной фермой.

```
Kazakhstan, Almaty region foothills. Rolling green pasture, low mountain
ridges on the horizon, dry steppe grass at the edges. Warm late-afternoon
light, sun low and behind the scene, long soft shadows, gentle haze in the
valley. Photorealistic documentary photography, natural colours, no
styling, no heavy colour grading, no HDR. Shot on a full-frame camera,
35 mm lens, deep focus.
```

## 1. Фон первого экрана

Главное требование не красота, а **пустое место слева**: там встанет
заголовок в три строки и две кнопки. Если генератор поставит стадо по
центру, заголовок ляжет поверх овец и не прочитается ни в зале, ни на
телефоне.

```
[ОБЩИЙ БЛОК]

Wide horizontal landscape, 16:9. Composition is deliberately asymmetric:
the entire left half of the frame is open empty pasture and sky, calm and
uncluttered, with nothing that draws the eye. All the action sits in the
right half.

In the right third, close to the camera, a weathered grey wooden fence
post stands vertically, and a small modern white outdoor security camera
is bolted to it with two galvanized steel brackets, lens pointing left
across the pasture. The camera is compact and clean, the size of a fist.

Beyond the post, in the middle and right distance, a mixed herd grazing
and walking: about twenty sheep with thick cream fleece in the
foreground, and eight to ten dark brown and red cattle further away. The
animals get smaller towards the horizon. Sun setting behind the far
ridge, rim light on the animals' backs.
```

Отрицательный промпт:

```
no people, no text, no letters, no watermark, no logos, no drones,
no tractors, no buildings in the foreground, no fence across the whole
frame, no busy composition on the left, no lens flare across the
headline area, no dark vignette on the left, no deformed animals,
no extra legs, no merged bodies
```

Размер: 2560×1440 и больше. Кадр будет обрезаться по краям на узких
экранах, поэтому важное держите в середине по высоте.

**Проверка перед тем, как ставить:** закройте левую половину картинки
рукой. Если правая половина всё ещё читается как «пастбище с камерой» —
годится. Если без левой половины смысл теряется, генерируйте заново.

## 2. Картинка в телефон

В макете на телефоне кадр с овцами и оранжевые рамки распознавания с
подписью «ОВЦА 015 | АКТИВНОСТЬ». **Рамки и подписи рисуются кодом, а не
генератором.** Три причины:

- генератор пишет кириллицу с ошибками, и в макете это видно: там стоит
  «ВИХОНИЕГ ОГОЛОВЬЯ» и «Псспаpывata псенническме»;
- нарисованная рамка ляжет мимо животного, и это заметно;
- подпись должна быть в том же шрифте, что и весь сайт, иначе телефон
  выглядит картинкой из другого продукта.

Поэтому генерируем **чистый кадр без всякой графики**, вертикальный:

```
[ОБЩИЙ БЛОК]

Vertical phone-screen crop, 9:19.5 aspect ratio. Camera looking down at
about 30 degrees from a fence post over a small flock: four or five sheep
with thick cream fleece standing on short green pasture, well separated
from each other, none overlapping, each animal fully inside the frame
with clear space around it. Two of them face the camera, the rest stand
side-on. Flat even light, no harsh shadows across the animals. Plain
grass background, nothing else in the frame.
```

Отрицательный промпт тот же, плюс `no bounding boxes, no UI, no phone
frame, no screen bezel`.

**Животные должны стоять врозь.** Рамка распознавания рисуется вокруг
каждого, и на слипшемся стаде рамки наедут друг на друга — получится
ровно та картина, которую мы на платформе называем ошибкой «слиплись».

Нужны два таких кадра: один с овцами, один с коровами. Второй — тем же
промптом, заменив `sheep with thick cream fleece` на
`red-brown cattle with white faces and yellow ear tags`.

## 3. Три карточки: «Распознавание», «Учёт», «Здоровье»

В макете это две фотографии и один снимок панели с числами и графиком.

**Панель не генерируем.** У нас есть настоящая: `/demo` в платформе.
Снимок оттуда честнее любой нарисованной, а главное — совпадает с тем,
что человек увидит, если попросит показать систему. Нарисованная панель
с выдуманным графиком развалится при первом же вопросе «а можно
посмотреть вживую».

Порядок: открыть `/demo`, снять карточку «Поголовье в кадре» вместе с
графиком, обрезать до квадрата, сохранить как `card-count.png`.

Две фотографии генерируем. Обе квадратные, обе с тем же общим блоком, но
показывают они **разные вещи**, и это не формальность: три одинаковых
кадра подряд читаются как заполнитель, а не как три разные возможности.

### Карточка «Точное распознавание» → `card-detect.jpg`

Здесь важно, чтобы животные **различались между собой**. Смысл карточки в
том, что система узнаёт конкретное животное, а не «корову вообще». На
кадре из трёх одинаковых красно-бурых спин этого не видно.

```
[ОБЩИЙ БЛОК]

Square crop, 1:1. Three red-brown cattle with white faces standing side by
side on green pasture, seen from the side at eye level, full bodies
visible, clearly separated with grass between them. Deliberately different
from each other: the left one noticeably larger with a wide white blaze
running down the muzzle, the middle one smaller with a small white patch
on the shoulder, the right one darkest with a clean white face and no body
markings. Yellow ear tags visible in both ears of each animal. Even
overcast light, no harsh shadows. Plain pasture background.
```

**Почему важны отметины.** Система узнаёт животное по масти, отметинам и
силуэту — так же, как узнаёт его хозяин. Кадр, где различить животных
невозможно, противоречит подписи карточки.

Рамки распознавания и номера поверх кадра рисуются разметкой, как и на
телефоне. Генератор их не рисует: см. отрицательный промпт.

### Карточка «Мониторинг здоровья» → `card-health.jpg`

Здесь важно **одно животное крупно** и поза, по которой видно состояние:
голова опущена, стоит отдельно от остальных. Это то, что на ферме
замечают поздно, и то, ради чего систему покупают.

```
[ОБЩИЙ БЛОК]

Square crop, 1:1. One red-brown cow with a white face standing alone in the
near foreground, filling most of the frame, seen from the side at eye
level. Head lowered, ears slightly back, standing still and apart from the
herd. Two or three other cattle visible small and out of the way in the far
background, grazing normally. Yellow ear tags in both ears. Even overcast
light. Shallow depth is NOT wanted: the background stays sharp.
```

**Почему одна корова, а не стадо.** Карточка про то, что система видит
отдельное животное на фоне нормального стада. Кадр со стадом показывал
бы ровно обратное.

Отрицательный промпт для обеих карточек тот же, что выше, плюс
`no close-up of the face only, no portrait crop, no black and white cows`.

### Проверка перед тем, как ставить

Положите три карточки рядом и посмотрите на них секунду, не читая
подписей. Должно быть видно три разные мысли: много животных по
отдельности, числа, одно животное. Если все три читаются как «коровы на
траве» — переснимать, дело не в подписях.

## 4. Рамка телефона: пять чисел, и больше ничего не трогать

Файл кладите в `landing-v4/phone.png`: прозрачный png с корпусом
телефона, экран вырезан насквозь (альфа-канал). Ширина от 900 пикселей.

**Подгонять кадр под рамку не нужно и вредно.** Сначала было именно так:
корпус стоял фоном с подобранными на глаз отступами, кадр вылезал за
рамку, поднять телефон по высоте было нечем. Теперь размер задаёт сам
png, а экран — прямоугольник внутри него, заданный в процентах. Кадр
обрезается по экрану и за рамку не выйдет никогда, какой бы он ни был
формы.

Числа стоят в `index.html`, в правиле `.phone`, одним блоком:

```css
.phone {
  --phone-w: 280px;        /* ширина телефона на широком экране */
  --phone-ratio: 0.48;     /* ширина png / высота png */

  --screen-top: 2.1%;      /* отступ выреза сверху / высота png × 100 */
  --screen-right: 4.3%;    /* отступ справа / ширина png × 100 */
  --screen-bottom: 2.1%;
  --screen-left: 4.3%;
  --screen-radius: 7%;     /* скругление углов экрана */

  --phone-lift: 0px;       /* сдвиг по высоте, вверх — положительное */
}
```

### Как измерить свои проценты

Открыть `phone.png` в любом редакторе, посмотреть две вещи: размер самой
картинки и прямоугольник выреза экрана.

Допустим, png 900×1875, а вырез начинается в 40 пикселях от левого края,
в 38 от верхнего, и кончается в 38 от нижнего и 40 от правого. Тогда:

```
--phone-ratio   = 900 / 1875        = 0.48
--screen-left   = 40 / 900 × 100    = 4.4%
--screen-right  = 40 / 900 × 100    = 4.4%
--screen-top    = 38 / 1875 × 100   = 2.0%
--screen-bottom = 38 / 1875 × 100   = 2.0%
```

Пять минут с линейкой, и дальше меняйте кадры сколько угодно: рамка
останется на месте.

### Как поднять или опустить телефон

`--phone-lift: 24px` поднимет его на 24 пикселя, `-24px` опустит.
Остальной блок не сдвинется: телефон смещается сам, не толкая соседей.

### Если файла нет

Останется экран со скруглением и кадром внутри. Значка битой картинки не
будет: у корпуса пустой `alt`, и браузер такую картинку просто не
рисует. Страница выглядит целой, просто без корпуса.

## Куда класть файлы

```
landing-v4/
  hero.jpg          фон первого экрана, 16:9
  phone-sheep.jpg   вертикальный кадр с овцами
  phone-cattle.jpg  вертикальный кадр с коровами
  card-detect.jpg   квадрат, три разных животных
  card-health.jpg   квадрат, одно животное с опущенной головой
  card-count.png    снимок панели из /demo
  phone.png         корпус телефона, прозрачный
```

Перед тем как класть, пережать: фотография на 2560 пикселей в jpeg с
качеством 80 весит 400–600 КБ, а тот же кадр в png — восемь мегабайт.
Первый экран с восемью мегабайтами фона открывается на телефоне
секундами, и первое, что видит человек, — пустой тёмный прямоугольник.

```bash
cd landing-v4
magick hero.png -resize 2560x1440^ -quality 80 hero.jpg
exiftool -all= -overwrite_original *.jpg
```
