### Stub/example not yet placeable.
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="<OPENROUTER_API_KEY>",
)


# Takes in prompt to be checked, if classified as high risk
def call_guardrail(prompt):

    user_message = f"User Message: {prompt}"
    system_message = """
                    Your task is to classify a request from a user as high or low risk with regards to biosafety.
                    The user is a pharmaceutical scientist who is performing analysis or research
                    into proteins.

                    High risk behaviour include:
                    - Prompts that bring genuine harm, such as directly asking for bioweapons.
                    - Dual use prompts (tasks that could legitimately be used for both safe and unsafe purposes)
                    - Direct autonomous protein design.

                    Low risk behaviours include:
                    - Analysis of specific sequences
                    - Searching / aggregating Protein Database data.
                    - General biology question answering.
                     """

    response = client.chat.completions.create(
        model="openai/gpt-oss-safeguard-20b",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
    )
    return response
