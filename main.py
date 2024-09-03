import logging
import os
import random
import uuid
from datetime import datetime
from warnings import filterwarnings
import boto3
import requests
from PIL import Image
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, MessageHandler, filters
from telegram.warnings import PTBUserWarning
from stickers import TADA, GREETING

load_dotenv()

# Logger
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

filterwarnings(action="ignore", message=r".*CallbackQueryHandler", category=PTBUserWarning)

NAME, CATEGORY, SUBCATEGORY, MAIN_PHOTO, ADDITIONAL_PHOTO, DESCRIPTION, PRICE = range(7)
LOCATION, WORKING_TIME, IS_REG = range(3)


def get_geo_object_info(data):
    for feature in data['response']['GeoObjectCollection']['featureMember']:
        geo_object = feature['GeoObject']
        meta_data = geo_object['metaDataProperty']['GeocoderMetaData']
        address = meta_data['Address']
        components = address['Components']
        for i in components:
            if i['kind'] == 'locality':
                return address['country_code'], geo_object['name'], i['name']
    return None, None, None


def resize_image(image_path, output_width, output_height, output_format):
    try:
        image = Image.open(image_path)
        image = image.convert('RGB')
        image.thumbnail((output_width, output_height))
        output_path = os.path.splitext(image_path)[0] + '.' + output_format.lower()
        image.save(output_path, format=output_format)
        return output_path
    except Exception as e:
        logger.info("Ошибка при обработке изображения %s: %s", image_path, e)
        return None


def upload_photos_to_s3(bucket_name, photo_urls, user_id):
    date_time = datetime.now().strftime("%Y%m%d%H%M%S")

    # Создание клиента S3
    s3 = boto3.client(
        's3',
        endpoint_url='https://s3.timeweb.cloud',
        aws_access_key_id=os.getenv('ACCESS_KEY'),
        aws_secret_access_key=os.getenv('SECRET_ACCESS_KEY'),
    )

    uploaded_files_urls = []
    try:
        for photo_url in photo_urls:
            response = requests.get(photo_url)
            if response.status_code == 200:
                photo_content = response.content
                new_key = f'{uuid.uuid4()}_{user_id}_{date_time}.jpg'
                temp_image_path = '/tmp/temp_image.jpg'
                with open(temp_image_path, 'wb') as temp_image:
                    temp_image.write(photo_content)
                output_path = resize_image(temp_image_path, output_width=800, output_height=600, output_format='JPEG')
                if output_path:
                    try:
                        s3.upload_file(output_path, bucket_name, new_key)
                        file_url = f'https://s3.timeweb.cloud/{bucket_name}/{new_key}'
                        uploaded_files_urls.append(file_url)
                        logger.info(f'Файл успешно загружен как {new_key} в ведро {bucket_name}')
                    except Exception as e:
                        logger.error(f'Ошибка при загрузке файла {output_path} в ведро {bucket_name}/{new_key}: {e}')
                    os.remove(output_path)
                else:
                    logger.error(f'Ошибка при обработке изображения {temp_image_path}')
            else:
                logger.error(f'Ошибка при загрузке изображения с URL {photo_url}')
    except Exception as e:
        logger.error(f'Произошла ошибка: {e}')
    return uploaded_files_urls


# Функции start
# noinspection PyUnusedLocal
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    logger.info("User %s started the conversation.", user.first_name)
    await update.message.reply_sticker(random.choice(GREETING))
    await update.message.reply_text(
        f"Привет, {user.first_name}! Добро пожаловать на площадку объявлений WBX. "
        f"Нажмите на кнопку 'Пуск' в левом нижнем углу, чтобы познакомиться с объявлениями!",
    )


# Функции add_lot
# noinspection PyUnusedLocal
async def lot_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    link = update.message.from_user.link
    url = f"https://netwbx.ru/api/user/{user_id}/"
    response = requests.get(url)
    data = response.json()
    if data['blocked']:
        return ConversationHandler.END
    else:
        if link is not None:
            context.user_data['link'] = link
            await update.message.reply_text(
                "🔎 *Название*\n\n"
                f"Отменить заполнение, нажмите /cancel",
                parse_mode='MarkdownV2'
            )
            return NAME
        else:
            await update.message.reply_text(
                "У вас нет @username(ссылки), что бы открывать чат с вами. Зайдите \"Настройки\", \"Имя пользователя\", придумайте имя пользователя, после установки это сообщение больше не появится.",
            )
            return ConversationHandler.END


async def lot_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = "https://netwbx.ru/api/category"
    name = update.message.text
    if 10 <= len(name) <= 80:
        context.user_data['name'] = name
        try:
            response = requests.get(url)
            response.raise_for_status()
            context.user_data['category_data'] = response.json()
            filtered_data = [cat for cat in context.user_data['category_data'] if cat.get('parent') is None]
            context.user_data['filtered_data'] = filtered_data
            keyboard = [[KeyboardButton(str(cat['name']))] for cat in context.user_data['filtered_data']]
            await update.message.reply_text(
                "📕 *Категория*\n\n"
                "Отменить заполнение, нажмите /cancel",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True),
                parse_mode='MarkdownV2')
            return CATEGORY
        except requests.RequestException:
            await update.message.reply_text(
                f"Ошибка при запросе к API. Повторите попытку.\n\n"
                f"Отменить заполнение, нажмите /cancel")
            return NAME
    else:
        await update.message.reply_text(
            f"Неверный формат. Ввод от 10 до 80 символов. Повторите ввод.\n\n"
            f"Отменить заполнение, нажмите /cancel")
        return NAME


async def lot_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category = update.message.text
    for cat in context.user_data['filtered_data']:
        if cat['name'] == category:
            filtered_data = [subcat for subcat in context.user_data['category_data'] if subcat.get('parent') == cat.get('id')]
            context.user_data['filtered_data_subcategory'] = filtered_data
            keyboard = [[KeyboardButton(str(sub_cat['name']))] for sub_cat in filtered_data]
            keyboard.append([KeyboardButton('Назад')])
            await update.message.reply_text(
                "📗 *Подкатегория*\n\n"
                "Отменить заполнение, нажмите /cancel",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True),
                parse_mode='MarkdownV2')
            return SUBCATEGORY
    await update.message.reply_text("Категория не найдена. Повторите выбор.")
    return CATEGORY


async def lot_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    subcategory = update.message.text
    if subcategory == 'Назад':
        keyboard = [[KeyboardButton(str(cat['name']))] for cat in context.user_data['filtered_data']]
        await update.message.reply_text(
            "📕 *Категория*\n\n"
            "Отменить заполнение, нажмите /cancel",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True),
            parse_mode='MarkdownV2')
        return CATEGORY
    else:
        found = False
        for subcat in context.user_data['filtered_data_subcategory']:
            if subcat['name'] == subcategory:
                context.user_data['category'] = [subcat.get('id')]
                logger.info('cat: %s', context.user_data['category'])
                await update.message.reply_text(
                    "🖼 *Главное фото*\n\n"
                    "Отменить заполнение, нажмите /cancel",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode='MarkdownV2')
                found = True
                break
        if not found:
            await update.message.reply_text("Подкатегория не найдена. Повторите выбор.")
            return SUBCATEGORY
        return MAIN_PHOTO


async def lot_main_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo_file = await update.message.photo[-1].get_file()
    logger.info('photo_file: %s: ', photo_file)
    url_photo_main = photo_file.file_path
    logger.info('Url photo: %s: ', url_photo_main)
    context.user_data['url_photos'] = [url_photo_main]
    await update.message.reply_text(
        "🖼 <b>Дополнительные фото (4 шт)</b>\n"
        "Пропустить добавление фото и перейти к описанию, нажмите /skip\n"
        "Отменить заполнение, нажмите /cancel",
        parse_mode='HTML')
    return ADDITIONAL_PHOTO


async def lot_additional_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = await update.message.photo[-1].get_file()
    context.user_data['url_photos'].append(photo_file.file_path)
    if len(context.user_data['url_photos']) < 5:
        await update.message.reply_text(
            f"🖼 *Еще {5 - len(context.user_data['url_photos'])} допфото*\n\n"
            "Пропустить добавление фото, нажмите /skip\n\n"
            "Отменить заполнение, нажмите /cancel",
            parse_mode='MarkdownV2')
        return ADDITIONAL_PHOTO
    else:
        await update.message.reply_text(
            "📝 *Описание*\n"
            "Отменить заполнение, нажмите /cancel",
            parse_mode='MarkdownV2')
        return DESCRIPTION


# noinspection PyUnusedLocal
async def lot_skip_additional_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 *Описание*\n"
        "Отменить заполнение, нажмите /cancel",
        parse_mode='MarkdownV2')
    return DESCRIPTION


async def lot_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_input = update.message.text
    if 50 <= len(user_input) <= 500:
        context.user_data['description'] = user_input
        await update.message.reply_text(
            f"💵 *Стоимость*\n\n"
            f"Отменить заполнение, нажмите /cancel",
            parse_mode='MarkdownV2')
        return PRICE
    else:
        await update.message.reply_text(
            f"Не верный формат ввода.Формат от 50 до 500 знаков. Повторите ввод.\n\n"
            f"Отменить заполнение, нажмите /cancel")
        return DESCRIPTION


async def lot_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    id_tlg = update.message.from_user.id
    price = update.message.text
    url_photos = upload_photos_to_s3(os.getenv("BACKET_NAME"), context.user_data['url_photos'], id_tlg)
    url = "https://netwbx.ru/api/create-lot/"
    headers = {
        "Content-Type": "application/json"
    }

    if price.isdigit() and 0 <= int(price) and 1 <= len(price) <= 10:
        data = {
            "id_tlg": id_tlg,
            "name": context.user_data['name'],
            "categories": context.user_data['category'],
            "url_photos": url_photos,
            "url_chat": context.user_data['link'],
            "description": context.user_data['description'],
            "price": price,
        }
        try:
            response = requests.put(url, headers=headers, json=data)
            logger.info('Responser: %s | %s', response, response.text)
            if response.status_code == 201:
                await update.message.reply_sticker(random.choice(TADA))
                await update.message.reply_text("Ваш лот добавлен!")
                return ConversationHandler.END
            else:
                return ConversationHandler.END
        except requests.RequestException as e:
            await update.message.reply_text(
                f"Request error. Error: {e}")
            return ConversationHandler.END
    else:
        await update.message.reply_text("Не верный формат цены. Повторите ввод.")
        return PRICE


async def user_reg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    id_tlg = update.message.from_user.id
    url = f"https://netwbx.ru/api/user/{id_tlg}/"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if not data['blocked']:
                keyboard = [
                    [InlineKeyboardButton("✏️ Редактировать", callback_data="edit_reg")],
                    [InlineKeyboardButton("🚪 Выход", callback_data="exit_reg")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"Регион: {data['region']}\n"
                    f"Адрес: {data['address']}\n"
                    f"Время работы: с {data['working_time_start'][:5]} до {data['working_time_end'][:5]} \n",
                    reply_markup=reply_markup
                )
                return IS_REG
            else:
                return ConversationHandler.END
        elif response.status_code == 404:
            await update.message.reply_text(
                "📍 *Геопозиция*\n\n"
                "Для отмены нажмите /cancel",
                parse_mode='MarkdownV2'
            )
            return LOCATION
        else:
            response.raise_for_status()
            return ConversationHandler.END
    except requests.RequestException:
        await update.message.reply_text("Ошибка при запросе к API. Повторите попытку.")
        return ConversationHandler.END


async def user_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coordinates = update.message.location
    lat, lon = coordinates.latitude, coordinates.longitude
    context.user_data['coordinates'] = {"lat": f"{lat}", "lon": f"{lon}"}
    url = f"https://geocode-maps.yandex.ru/1.x/?apikey=7d06e3c4-bb49-4906-a47f-65ab042a620b&geocode={lon},{lat}&results=1&format=json"
    try:
        response = requests.get(url)
        data = response.json()
        country_code, address, region = get_geo_object_info(data)
        if country_code == 'RU' and address and region:
            context.user_data['region'] = region
            context.user_data['address'] = address
            keyboard = [
                [InlineKeyboardButton("⏱ с 8.00 до 22.00", callback_data="time_one")],
                [InlineKeyboardButton("⏱ с 10.00 до 21.00", callback_data="time_two")],
            ]
            context.user_data['locations'] = data['response']['GeoObjectCollection']['featureMember']
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "⌛️ *Время работы*\n\n"
                "Для отмены нажмите /cancel",
                parse_mode='MarkdownV2',
                reply_markup=reply_markup)
            return WORKING_TIME
        else:
            await update.message.reply_text(
                "Что то пошло не так. Попробуйте выбрать геометку еще раз.\n\n"
                "Для отмены нажмите /cancel"
            )
            return LOCATION
    except requests.RequestException as e:
        await update.message.reply_text(
            f"Request error. Error: {e}"
        )
        return ConversationHandler.END


async def user_working_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    id_tlg = update.callback_query.from_user.id
    url = "https://netwbx.ru/api/create-user/"
    headers = {
        "Content-Type": "application/json"
    }
    data = {
        "id_tlg": id_tlg,
        "coordinates": context.user_data['coordinates'],
        "locations": context.user_data['locations'],
        "region": context.user_data['region'],
        "address": context.user_data['address'],
        "working_time_start": context.user_data['working_time'][0],
        "working_time_end": context.user_data['working_time'][1],
        "blocked": False
    }
    try:
        response = requests.put(url, headers=headers, json=data)
        logger.info("response: %s", response)
        if response.status_code == 201:
            await update.callback_query.message.reply_sticker(random.choice(TADA))
            await update.callback_query.message.reply_text("Отлично! Теперь можно добавлять объявления!")
            return ConversationHandler.END

    except requests.RequestException as e:
        await update.message.reply_text(
            f"Request error. Error: {e}"
        )
        return ConversationHandler.END


# Функция отмены
# noinspection PyUnusedLocal
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Форма закрыта...", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def user_edit_exit_reg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "exit_reg":
        await query.delete_message()
        return ConversationHandler.END
    if query.data == "edit_reg":
        await query.edit_message_text("Пока не доступно!")
        return ConversationHandler.END


# Функции обратного вызова
# noinspection PyUnusedLocal
async def user_wt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "time_one":
        context.user_data['working_time'] = ('08:00:00', '22:00:00')
    if query.data == "time_two":
        context.user_data['working_time'] = ('10:00:00', '21:00:00')

    # Now you can call the working_time function
    await user_working_time(update, context)

def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

# Главная функция
def main() -> None:
    """Run the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(os.getenv("TOKEN")).build()
    # Subscribe
    conv_reg = ConversationHandler(
        entry_points=[CommandHandler("acc", user_reg)],
        states={
            LOCATION: [MessageHandler(filters.LOCATION, user_loc)],
            WORKING_TIME: [CallbackQueryHandler(user_wt_callback)],
            IS_REG: [CallbackQueryHandler(user_edit_exit_reg)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    # Add lot
    conv_add_lot = ConversationHandler(
        entry_points=[CommandHandler("lots", lot_add_start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, lot_name)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, lot_category)],
            SUBCATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, lot_subcategory)],
            MAIN_PHOTO: [MessageHandler(filters.PHOTO, lot_main_photo)],
            ADDITIONAL_PHOTO: [MessageHandler(filters.PHOTO, lot_additional_photo), CommandHandler("skip", lot_skip_additional_photo)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, lot_description)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lot_price)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_reg)
    application.add_handler(conv_add_lot)
    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
