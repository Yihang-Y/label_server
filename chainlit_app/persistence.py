import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from config import DB_CONNINFO

@cl.data_layer
def data_layer():
    return SQLAlchemyDataLayer(conninfo=DB_CONNINFO)
