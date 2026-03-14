"""Chainlit entry point for listen-wiseer."""

import chainlit as cl


@cl.on_chat_start
async def start():
    await cl.Message(
        content=(
            "Welcome to **listen-wiseer**!\n\n"
            "Ask me about your Spotify listening history, "
            "get recommendations, or create a new playlist."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    # TODO: route through LangGraph agent
    await cl.Message(content=f"[stub] received: {message.content}").send()
