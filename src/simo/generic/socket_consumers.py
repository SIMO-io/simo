import asyncio
#import cv2
import base64
import time
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from simo.users.middleware import introduce
from simo.core.models import Component



class CamStreamConsumer(AsyncWebsocketConsumer):
    live = True
    component = None
    video = None

    async def connect(self):
        await self.accept()

        if not self.scope['user'].is_authenticated:
            return self.close()
        if not self.scope['user'].is_active:
            return self.close()

        introduce(self.scope['user'])

        try:
            self.component = await sync_to_async(
                Component.objects.get, thread_sensitive=True
            )(
                pk=self.scope['url_route']['kwargs']['component_id'],
            )
        except:
            return self.close()

        can_read = await sync_to_async(
            self.component.can_read, thread_sensitive=True
        )(self.scope['user'])
        if not can_read:
            return self.close()

        # self.video = cv2.VideoCapture(self.component.config['rtsp_address'])
        # asyncio.create_task(self.send_cam())


    async def send_cam(self):
        every_frame = 4
        current_frame = 0
        while self.live:
            _, frame = self.video.read()
            #_, jpeg = cv2.imencode('.jpg', frame)
            current_frame += 1
            if current_frame >= every_frame:
                await self.send(
                    text_data=base64.b64encode(jpeg.tobytes()).decode('ascii')
                )
                current_frame = 0
            await asyncio.sleep(0)


    async def disconnect(self, code):
        self.live = False
        self.video.release()
